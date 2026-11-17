# Open TODO items and questions

## A. Required inputs (blocking real device integration)
1. **Software/API versions** for ISE, Catalyst Center, APIC, NX-OS, IOS-XE, Splunk ES, ESXi/vSphere, Ekahau (which product: AI Pro, Cloud or other). Interface choices below are *candidates to verify*, not confirmed.
2. **Workflow list and parameters per platform.** All 7 shipped workflows are ASSUMPTION samples (Ekahau Design is a launcher tile, not a workflow).
3. **Which automation backend** performs the changes (e.g. an automation/orchestration platform, CI system or ITSM tool), its API, authentication and job/status/log format. The portal is a front end only; this is the main blocker.
4. **Dispatch definitions**: every sample workflow has `dispatch: {backend: TODO, job: TODO}` (no job names, endpoints or payloads were invented). What variables does each backend job expect?
5. **Backend integration class**: not written (two methods: `submit`, `poll`). Needs service authentication, TLS/CA handling, timeouts, error mapping, and use of the run id as an idempotency key.
6. **Device inventory and management IPs** (config only), and optional `console_url` links to each platform's own console. Shipped `inventory.example.yaml` is placeholder (192.0.2.0/24).
7. **Service credential for the backend**: where the portal gets the one token/account it uses to call the backend (env, Vault, CyberArk, cloud secret manager). Device credentials stay in the backend.
8. **Device authentication model**: should device access (inside the backend) go through TACACS+/RADIUS (e.g. via ISE) rather than service accounts? Portal login stays local, as requested.
9. **Hosting environment** and whether outbound internet is allowed (affects TLS termination, DB choice, single vs multiple instances, package mirrors).
10. **Brand assets**: may official Cisco logo, fonts and colours be used? Until confirmed the theme is a neutral placeholder.

## B. Questions on scope
11. "VMware ESXi management server": standalone ESXi hosts, or vCenter?
11b. Ekahau Design (launcher tile): the https address of the Ekahau environment on VMware (`launchers.ekahau.url`), the Ekahau product/version, and how users reach it (web, remote-desktop gateway, other). Should a launch require a specific role? Single sign-on into Ekahau is not provided.
12. Which platforms' workflows are read-only vs write? Which need a **second approver** (e.g. disabling a Splunk correlation search, ESXi maintenance mode)?
13. Should engineers see all runs (current ASSUMPTION) or only their own?
14. Is the optional **Viewer** role wanted? (Implemented; trivial to remove.)
15. Lockout policy: auto-unlock after 15 min (ASSUMPTION) vs admin-only unlock (`PORTAL_LOCKOUT_MINUTES=0`).
16. Password policy beyond min length 12; rotation or breach-list checks wanted?
17. Audit retention period and where it must be shipped (SIEM/Splunk).

## C. Known gaps in the delivered code
18. **Preview is request-only**: the portal does not read devices, so there is no before/after diff (optional backend "check mode" TODO).
19. **Rollback** is the backend's responsibility; the portal only reports the backend's final state.
20. No per-device/workflow **locking** in the portal; two engineers can submit against the same device concurrently (the backend may serialise).
21. No **MFA/SSO**, no per-IP **rate limiting** (use the reverse proxy), no email/notification on lockout.
22. Audit log is append-only at the DB-trigger level only; true tamper evidence needs an external write-once sink.
23. SQLite and in-process worker threads: single instance only. Runs interrupted by restart are marked failed.
24. No role change in the admin UI (only create/disable/enable/reset/unlock, as specified).
25. Cost/limits of `argon2` parameters not tuned to the production host.
26. Accessibility: automated contrast check only; manual screen-reader/keyboard audit not done.
27. Preview/run history has no pagination beyond the latest 100 runs.
