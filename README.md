# Network Automation Portal

Internal web portal: an engineer picks a predefined workflow for a platform, fills in a validated form,
reviews a **dry-run preview**, **explicitly confirms**, and watches the run and its log.
Platforms: Cisco ISE, Cisco SDA (Catalyst Center), Cisco ACI (APIC), NX-OS, Catalyst IOS-XE,
Splunk Enterprise Security, VMware ESXi.

> **Status: framework complete, device integrations not yet connected.**
> No device API calls, endpoints or object models are included, because the software versions,
> workflow list and interfaces have not been confirmed (see [OPEN_ITEMS.md](OPEN_ITEMS.md)).
> Every workflow shipped is an **ASSUMPTION** sample whose device request is `TODO`.
> The portal defaults to **dry-run**: confirming a run simulates it and contacts no device.

## 1. Recommended stack and structure

**Recommendation: Python 3.11+ · FastAPI · server-rendered Jinja2 templates · SQLite · argon2-cffi · PyYAML.**

Why (ASSUMPTION: small internal team, single instance, hosting not yet known):

| Choice | Reason |
|---|---|
| Python | Network automation teams already know it; every device interface under consideration (RESTCONF, NETCONF, NX-API, REST, vSphere) has mature Python libraries for later adapters. |
| Server-rendered HTML, almost no JS | Smallest attack surface, strict CSP (`script-src 'self'`, no inline script/style), forms work with keyboard and screen readers by default. Only JS: focus-on-error and log polling. |
| FastAPI | Typed, small, easy to test; used here only as a routing layer. |
| SQLite (stdlib) | No extra service to run. Plain SQL, so a move to PostgreSQL is mechanical if the hosting answer requires multiple instances. |
| argon2id | Current recommended password hash; salt generated per hash. |
| YAML workflow config | New workflows need no code change; validated at startup. |

```
app/
  main.py          app factory, security headers, error pages
  settings.py      env-var configuration
  db.py            schema (users, sessions, runs, run_log, audit_log) + append-only audit triggers
  security.py      argon2id hashing, password policy, tokens
  users.py         user store, authentication, lockout
  sessions.py      server-side sessions, idle + absolute timeout
  audit.py redact.py   append-only audit trail and secret redaction
  workflows.py     workflow config loader/validator, parameter validation, dry-run plan
  runner.py        preview -> confirm -> execute lifecycle, adapter registry
  inventory.py credentials.py   device inventory and secret lookup (names only, never values)
  routes/          auth, dashboard+platform, runs, admin (users + audit)
  templates/ static/   UI (theme.css = neutral placeholder tokens)
config/
  workflows.yaml           workflow catalogue (all ASSUMPTION samples)
  inventory.example.yaml   placeholder devices (copy to inventory.yaml)
tests/                     25 tests: auth, lockout, timeouts, CSRF, roles, flow, audit, contrast
```

## 2. Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp config/inventory.example.yaml config/inventory.yaml   # edit; placeholders use 192.0.2.0/24
export PORTAL_COOKIE_SECURE=true                          # see below for local HTTP dev
python -m app.cli create-admin <username>                 # hidden password prompt
python -m uvicorn app.main:app_factory --factory --host 127.0.0.1 --port 8000
python -m pytest
```

Run behind a TLS-terminating reverse proxy (needed: session cookies are `Secure`). Start uvicorn with
`--proxy-headers --forwarded-allow-ips=<proxy ip>` so audit records get real client IPs.
For local plain-HTTP development only, set `PORTAL_COOKIE_SECURE=false` (logged as a warning).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORTAL_COOKIE_SECURE` | `true` | Mark cookies `Secure` (also enables HSTS and the `__Host-` cookie prefix). |
| `PORTAL_SESSION_IDLE_MINUTES` | `15` | Idle timeout. Status polling does not extend it. |
| `PORTAL_SESSION_ABSOLUTE_HOURS` | `8` | Hard session lifetime. |
| `PORTAL_MAX_FAILED_ATTEMPTS` | `5` | Failed sign-ins before the account locks. |
| `PORTAL_LOCKOUT_MINUTES` | `15` | Lock duration; `0` = until an admin unlocks. (ASSUMPTION) |
| `PORTAL_PASSWORD_MIN_LENGTH` | `12` | Minimum password length (>= 8). |
| `PORTAL_EXECUTION_MODE` | `dry_run` | `dry_run` or `live`. Live is meaningless until adapters exist. |
| `PORTAL_PREVIEW_TTL_MINUTES` | `30` | Preview expiry; confirm after this requires a new preview. |
| `PORTAL_MAX_CONCURRENT_RUNS` | `4` | Worker threads. |
| `PORTAL_DB_PATH` | `data/portal.db` | SQLite file (created with mode 0600). |
| `PORTAL_WORKFLOWS_FILE` / `PORTAL_INVENTORY_FILE` | `config/...` | Config locations. |
| `PORTAL_AUDIT_JSONL_FILE` | unset | Optional JSON-lines mirror of the audit log for a SIEM. |
| `PORTAL_SECRETS_DIR` | unset | Directory of secret files (Docker/Kubernetes secret mounts). |
| `PORTAL_CRED_<REF>_USERNAME` / `_PASSWORD` | – | Device credentials. `<REF>` is the inventory `credential_ref`, upper-cased, non-alphanumerics → `_` (`ise-lab` → `ISE_LAB`). |
| `PORTAL_TITLE` | `Network Automation Portal` | Header text. |

### Running as an HTTPS web portal (Docker)

`docker-compose.https.yml` runs the portal behind Caddy, which terminates TLS. The portal itself is not exposed to the network.

```bash
echo 'PORTAL_DOMAIN=portal.example.internal' > .env      # the DNS name users will open
# PORTAL_TLS (optional, in .env):
#   internal                       Caddy's own CA (default; clients must trust it)
#   admin@yourcompany.example      Let's Encrypt (public DNS, ports 80/443 reachable from the internet)
#   /certs/cert.pem /certs/key.pem your own certificate: put the files in ./certs
docker compose -f docker-compose.https.yml build
docker compose -f docker-compose.https.yml run --rm portal python -m app.cli create-admin admin
docker compose -f docker-compose.https.yml up -d
```

Open `https://<PORTAL_DOMAIN>`. The DNS name must resolve to the host; firewall: allow 443 (and 80 for Let's Encrypt) only from the networks that need it.
This setup keeps `PORTAL_COOKIE_SECURE=true`, so cookies are `Secure` and HSTS is sent. It is **untested in CI** (no container runtime was available while writing it).
Production checklist: restrict source networks, back up the `portal-data` volume (users + audit log), ship the audit JSONL to your SIEM, supply device credentials through secrets (not git), and keep `PORTAL_EXECUTION_MODE=dry_run` until adapters are written and approved.

## 3. Login flow and user store

* `users` table: `username` (unique, case-insensitive), `password_hash` (argon2id, per-hash random salt),
  `role` (`admin`/`engineer`/`viewer`), `is_active`, `failed_attempts`, `locked_until`,
  `must_change_password`, timestamps. Plaintext passwords are never stored or logged
  (tests assert the DB file contains none).
* Sign-in: constant-work check (dummy hash for unknown users), one generic failure message
  (no user enumeration; the real reason goes to the audit log). After N failures the account locks;
  a correct password is still refused while locked. Admin can unlock. Hashes are upgraded on login if parameters change.
* Sessions: random 256-bit token in a cookie (`HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` prefix, no max-age);
  only its SHA-256 is stored server-side. Idle and absolute timeouts are enforced server-side.
  Disabling a user or resetting/changing a password revokes their sessions.
* CSRF: per-session token on every POST (and double-submit token on the login form).
* Roles: **admin** (manage users + run workflows + audit log), **engineer** (run workflows),
  **viewer** (read-only; implemented because cheap, easy to remove). ASSUMPTION: all signed-in users may view all runs.
* Admin creates users (random temporary password shown once, change forced at first sign-in), disables/enables,
  resets (new temporary password shown once), unlocks. Cannot disable self or the last active admin.
* First admin: `python -m app.cli create-admin <name>` (password never on the command line).

## 4. Workflow lifecycle and safety

1. **Form** generated from the workflow's parameter definitions; server-side validation (types, ranges, regex,
   inventory membership; control characters and newlines rejected).
2. **Preview (dry-run)**: the plan is computed from your inputs and stored with a hash. It is *not* compared with
   live device state (TODO: needs read adapters).
3. **Confirm**: explicit POST by the user who created the preview. The server re-checks status, expiry, plan hash and
   that `workflows.yaml` has not changed since; a double-submit starts the run once.
4. **Run**: background thread; each step is logged. In `dry_run` mode no device is contacted. In `live` mode a step runs
   only if its request is defined (not `TODO`), an adapter is registered for its interface, and the credential exists.
   On failure the run stops; there is no automatic rollback (TODO).
5. **Status/log** page with polling; everything is audited (`workflow.preview`, `workflow.confirm`, `workflow.run`).

### Adding a workflow (no code change)

Edit `config/workflows.yaml`, restart the portal (a bad file stops startup and lists every problem):

```yaml
workflows:
  - id: nxos-create-vlan            # unique, lowercase, dashes
    platform: nxos                  # must exist under `platforms:`
    title: Create VLAN
    description: Create a VLAN on an NX-OS switch.
    risk: low                       # low | medium | high
    assumption: true                # shows an ASSUMPTION badge; remove once the workflow is confirmed
    parameters:                     # types: string int bool enum ip cidr hostname device
      - {name: device, label: Switch, type: device}
      - {name: vlan_id, label: VLAN ID, type: int, min: 2, max: 3967}
      - {name: vlan_name, label: VLAN name, type: string, pattern: '[A-Za-z0-9_-]{1,32}', max_length: 32}
    plan:
      summary: "Create VLAN {vlan_id} on {device}"
      steps:
        - id: create-vlan
          description: "Create VLAN {vlan_id} named '{vlan_name}'"
          interface: nxos-api       # must match a registered adapter name
          write: true
          request: TODO             # replace with a mapping once the interface is confirmed
```

Rules: `{name}` placeholders must match parameters; parameter names that look like secrets
(`password`, `token`, `secret`, `community`, `key`, …) are rejected; secrets come from the credential store.
Once an interface is confirmed, set `request:` to a mapping (e.g. method/path/body as defined by the vendor
documentation for your version); string values are placeholder-substituted. Then register an adapter:

```python
from app.runner import register_adapter
class MyAdapter:                    # implements execute(device, credentials, request) -> str
    ...
register_adapter("nxos-api", MyAdapter())
```

Adapters are intentionally not shipped: auth schemes and endpoints differ per platform and version, and none are confirmed.

## 5. Security notes

* Passwords: argon2id; password length capped at 256 before hashing; policy: min length, no username, not trivially repetitive.
* Headers: strict CSP (no inline script/style), `frame-ancestors 'none'`, `nosniff`, HSTS when Secure, `Cache-Control: no-store` on dynamic pages.
* Audit log: append-only (SQLite triggers reject UPDATE/DELETE); records actor, role, time, action, target,
  redacted parameters, result, IP. Params with secret-like keys and `password=…`-style text are masked; credentials
  never enter params, logs or templates. Optional JSONL mirror for a SIEM. *Limitation:* a database owner can still alter the file;
  ship the JSONL to a write-once store for real tamper evidence.
* Device credentials: read at execution time from env or `PORTAL_SECRETS_DIR`; `Credentials` repr is masked, run logs scrub
  known credential values; the UI shows only "configured: yes/no".
* Not included (see OPEN_ITEMS): per-IP rate limiting (do it at the proxy), MFA/SSO, four-eyes approval, per-device locks, rollback.
* Keep `data/`, `.env` and `config/inventory.yaml` out of git (already in `.gitignore`); file permissions 0600/0700.

## 6. Look and feel, accessibility

Card-based light layout with a blue accent, system font stack. **Neutral placeholder theme: not Cisco branding.**
No Cisco colours, fonts or logos are used because permission is unconfirmed (TODO). To apply approved branding,
edit only `app/static/css/theme.css` (tokens) and the `TODO(brand)` spot in `templates/base.html`.
Accessibility: skip link, landmarks, labelled fields with `aria-describedby`, error summary that receives focus,
visible focus ring, 44px targets, responsive down to phone width, reduced-motion and forced-colors support.
`tests/test_contrast.py` fails the build if any token pair drops below WCAG 2.1 AA (4.5:1 text, 3:1 controls).
A full AA claim still needs a manual screen-reader and keyboard pass (TODO).
