# Cisco & Splunk Lab Portal

Internal web portal: an engineer picks a predefined workflow for a platform, fills in a validated form,
reviews a **dry-run preview**, **explicitly confirms**, and watches the run and its log.
Platforms: Cisco ISE, Cisco SDA (Catalyst Center), Cisco ACI (APIC), NX-OS, Catalyst IOS-XE,
Splunk Enterprise Security, VMware ESXi, Ekahau Design (a launcher tile that opens the Ekahau environment hosted on VMware).

> **This portal is a front end, not a configuration engine.** It collects and validates a request, shows a
> preview, records the engineer's explicit approval, and hands the request to a separate **automation backend**
> that performs the change on the devices. The portal never connects to a device and holds **no device
> credentials**; those live in the backend.
>
> **Status: framework complete, backend not yet connected.** The backend product (for example an automation
> or orchestration platform), its API, and the platform versions have not been confirmed (see
> [OPEN_ITEMS.md](OPEN_ITEMS.md)), so none is included. Every workflow shipped is an **ASSUMPTION** sample whose
> `dispatch` (backend and job) is `TODO`. The portal defaults to **dry-run**: a confirmed run is simulated and
> nothing is sent anywhere.

```
Engineer ──> Portal (form, validation, preview, approval, audit) ──> Automation backend ──> Devices
                         ▲                                                  │
                         └───────── status + log mirrored back ─────────────┘
```

**Language:** the portal interface is in Bahasa Indonesia (this documentation stays in English; audit action codes such as `workflow.preview` stay in English on purpose). The top menu has **Inovasi** with two items, *Metrodata AI Use Case* and *Splunk Innovation* (defined under `innovation:` in `config/workflows.yaml`). Each opens a page whose external link opens in a new tab once its https address is set in `config/inventory.yaml` under `launchers:` (keys `metrodata-ai-use-case`, `splunk-innovation`); until then the page shows a TODO. *Metrodata AI Use Case* is itself a small dashboard with three cards, each with its own icon and short explanation: **Joint Planning Session**, **Go To Market** and **Document Procurement** (`use_cases:` in `config/workflows.yaml`; their addresses use the keys `joint-planning-session`, `go-to-market`, `document-procurement`). The card descriptions are ASSUMPTION drafts. **Go To Market** opens https://metrodata-ai-gtm.netlify.app and **Joint Planning Session** opens https://metrodata-ai-jps.netlify.app (default `url:` in `config/workflows.yaml`; an entry in `inventory.yaml` overrides it); Document Procurement still has no address (TODO). Launches are audited as `innovation.launch`.

The portal also links each platform's devices to their own native consoles (optional `console_url`), and the **Ekahau Design** tile is a launcher: one click opens the Ekahau environment (hosted on VMware) in a new tab. Set its address in `config/inventory.yaml` under `launchers: {ekahau: {url: https://...}}` (https only). No credentials are passed and each launch is audited as `platform.launch`.

## 1. Recommended stack and structure

**Recommendation: Python 3.11+ · FastAPI · server-rendered Jinja2 templates · SQLite · argon2-cffi · PyYAML.**

Why (ASSUMPTION: small internal team, single instance, hosting not yet known):

| Choice | Reason |
|---|---|
| Python | Network automation teams already know it; every device interface under consideration (RESTCONF, NETCONF, NX-API, REST, vSphere) has mature Python libraries if a backend integration needs one. |
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
  runner.py        preview -> confirm -> hand-off to the automation backend -> mirror status; backend registry
  inventory.py     device inventory (names, addresses, optional console links; no credentials)
  routes/          auth, dashboard+platform, runs, admin (users + audit)
  templates/ static/   UI (theme.css = neutral placeholder tokens)
config/
  workflows.yaml           workflow catalogue (all ASSUMPTION samples)
  inventory.example.yaml   placeholder devices (copy to inventory.yaml)
tests/                     33 tests: auth, lockout, timeouts, CSRF, roles, flow, audit, contrast
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
| `PORTAL_EXECUTION_MODE` | `dry_run` | `dry_run`: nothing is sent to the backend. `live`: confirmed requests are submitted to the backend (needs a registered backend). |
| `PORTAL_BACKEND_POLL_SECONDS` | `3` | How often the portal asks the backend for job status. |
| `PORTAL_BACKEND_TIMEOUT_SECONDS` | `900` | Stop waiting after this long; the backend job may still be running. |
| `PORTAL_PREVIEW_TTL_MINUTES` | `30` | Preview expiry; confirm after this requires a new preview. |
| `PORTAL_MAX_CONCURRENT_RUNS` | `4` | Worker threads. |
| `PORTAL_DB_PATH` | `data/portal.db` | SQLite file (created with mode 0600). |
| `PORTAL_WORKFLOWS_FILE` / `PORTAL_INVENTORY_FILE` | `config/...` | Config locations. |
| `PORTAL_AUDIT_JSONL_FILE` | unset | Optional JSON-lines mirror of the audit log for a SIEM. |
| `PORTAL_TITLE` | `Cisco & Splunk Lab Portal` | Header text. |

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
Production checklist: restrict source networks, back up the `portal-data` volume (users + audit log), ship the audit JSONL to your SIEM, keep any backend service credential out of git, and keep `PORTAL_EXECUTION_MODE=dry_run` until the backend integration is written and approved.

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
2. **Preview**: the request is built from your inputs and stored with a hash: a readable list of changes, the
   backend/job it will be handed to, and the exact data that will be sent. It is *not* a diff against device state
   (the portal never reads devices; TODO: optional backend "check mode").
3. **Confirm**: explicit POST by the user who created the preview. The server re-checks status, expiry, plan hash and
   that `workflows.yaml` has not changed since; a double-submit sends the request once.
4. **Hand-off**: in `dry_run` mode nothing is sent. In `live` mode the portal submits the request to the registered
   backend (with the run id as an idempotency key), then polls it and mirrors its log and final state into the run page.
   It refuses if `dispatch` is `TODO` or no backend is registered. A timeout only stops the portal waiting; the backend
   job may still be running, and the run page shows the backend job id to check there. No rollback is done by the portal.
5. **Status/log** page with polling; everything is audited (`workflow.preview`, `workflow.confirm`, `workflow.run`).

### Connecting an automation backend (code, once)

Implement two methods and register it under a name; the workflow then refers to that name:

```python
from app.runner import JobStatus, register_backend

class MyBackend:
    def submit(self, job: dict) -> str:
        # job = {run_id, requested_by, workflow_id, platform, backend_job, targets, payload}
        # Call the backend's API here (authenticate with a service credential from the environment
        # or secret store; never log it) and return the backend's job id.
        ...
    def poll(self, job_id: str) -> JobStatus:
        # JobStatus(state="pending"|"running"|"succeeded"|"failed", lines=[full log so far], summary="")
        ...

register_backend("my-backend", MyBackend())   # e.g. at startup in app/main.py
```

TODO: which backend product, its API and authentication, and its log/status format are not yet known, so none is shipped.

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
    plan:                           # readable preview lines only; the portal does not execute them
      summary: "Create VLAN {vlan_id} on {device}"
      steps:
        - id: create-vlan
          description: "Create VLAN {vlan_id} named '{vlan_name}'"
          write: true
    dispatch:
      backend: TODO                 # registered backend name
      job: TODO                     # job/playbook/template id inside that backend
      # payload:                    # optional; omitted = all validated parameters are sent as-is
      #   vlan: "{vlan_id}"         # a lone {x} keeps its type (int stays int)
```

Rules: `{name}` placeholders must match parameters; parameter and payload names that look like secrets
(`password`, `token`, `secret`, `community`, `key`, …) are rejected. Old `interface:`/`request:` step keys are no longer
accepted, because the portal does not call devices.

## 5. Security notes

* Passwords: argon2id; password length capped at 256 before hashing; policy: min length, no username, not trivially repetitive.
* Headers: strict CSP (no inline script/style), `frame-ancestors 'none'`, `nosniff`, HSTS when Secure, `Cache-Control: no-store` on dynamic pages.
* Audit log: append-only (SQLite triggers reject UPDATE/DELETE); records actor, role, time, action, target,
  redacted parameters, result, IP. Params with secret-like keys and `password=…`-style text are masked; credentials
  never enter params, logs or templates. Optional JSONL mirror for a SIEM. *Limitation:* a database owner can still alter the file;
  ship the JSONL to a write-once store for real tamper evidence.
* Device credentials: **none in the portal.** The automation backend holds them. The portal needs at most one
  service credential to call the backend (read from the environment/secret store inside your backend class, never shown).
  Backend log lines are scrubbed of `password=`/`token=`-style text before being stored.
* Not included (see OPEN_ITEMS): per-IP rate limiting (do it at the proxy), MFA/SSO, four-eyes approval, per-device locks.
* Keep `data/`, `.env` and `config/inventory.yaml` out of git (already in `.gitignore`); file permissions 0600/0700.

## 6. Look and feel, accessibility

Card-based light layout with a blue accent, a generic line icon beside each platform (`icon:` in `workflows.yaml`; drawn in `templates/_icons.html`, no vendor logos), system font stack. **Neutral placeholder theme: not Cisco branding.**
No Cisco colours, fonts or logos are used because permission is unconfirmed (TODO). To apply approved branding,
edit only `app/static/css/theme.css` (tokens) and the `TODO(brand)` spot in `templates/base.html`.
Accessibility: skip link, landmarks, labelled fields with `aria-describedby`, error summary that receives focus,
visible focus ring, 44px targets, responsive down to phone width, reduced-motion and forced-colors support.
`tests/test_contrast.py` fails the build if any token pair drops below WCAG 2.1 AA (4.5:1 text, 3:1 controls).
A full AA claim still needs a manual screen-reader and keyboard pass (TODO).
