# Open TODO items and questions

## A. Required inputs (blocking real device integration)
1. **Software/API versions** for ISE, Catalyst Center, APIC, NX-OS, IOS-XE, Splunk ES, ESXi/vSphere. Interface choices below are *candidates to verify*, not confirmed.
2. **Workflow list and parameters per platform.** All 7 shipped workflows are ASSUMPTION samples.
3. **Confirmed interface per platform**: ISE (ERS vs OpenAPI), Catalyst Center REST, APIC REST, NX-OS (NX-API vs RESTCONF), IOS-XE (RESTCONF vs NETCONF), Splunk REST, vSphere API.
4. **Request definitions**: every sample step has `request: TODO` (no endpoint, payload or object model was invented).
5. **Adapters**: none written. Each needs authentication (token/session/basic), TLS verification and CA handling, timeouts, error mapping.
6. **Device inventory and management IPs** (config only). Shipped `inventory.example.yaml` is placeholder (192.0.2.0/24).
7. **Device credential store**: env/secret files supported; confirm whether Vault, CyberArk or a cloud secret manager is required.
8. **Device authentication model**: should device access go through TACACS+/RADIUS (e.g. via ISE) rather than service accounts? Portal login stays local, as requested.
9. **Hosting environment** and whether outbound internet is allowed (affects TLS termination, DB choice, single vs multiple instances, package mirrors).
10. **Brand assets**: may official Cisco logo, fonts and colours be used? Until confirmed the theme is a neutral placeholder.

## B. Questions on scope
11. "VMware ESXi management server": standalone ESXi hosts, or vCenter?
12. Which platforms' workflows are read-only vs write? Which need a **second approver** (e.g. disabling a Splunk correlation search, ESXi maintenance mode)?
13. Should engineers see all runs (current ASSUMPTION) or only their own?
14. Is the optional **Viewer** role wanted? (Implemented; trivial to remove.)
15. Lockout policy: auto-unlock after 15 min (ASSUMPTION) vs admin-only unlock (`PORTAL_LOCKOUT_MINUTES=0`).
16. Password policy beyond min length 12; rotation or breach-list checks wanted?
17. Audit retention period and where it must be shipped (SIEM/Splunk).

## C. Known gaps in the delivered code
18. **Dry-run is plan-only**: no read of live device state, so no true before/after diff.
19. No **rollback**; a failed step stops the run and leaves earlier steps applied.
20. No per-device/workflow **locking**; two engineers can run against the same device concurrently.
21. No **MFA/SSO**, no per-IP **rate limiting** (use the reverse proxy), no email/notification on lockout.
22. Audit log is append-only at the DB-trigger level only; true tamper evidence needs an external write-once sink.
23. SQLite and in-process worker threads: single instance only. Runs interrupted by restart are marked failed.
24. No role change in the admin UI (only create/disable/enable/reset/unlock, as specified).
25. Cost/limits of `argon2` parameters not tuned to the production host.
26. Accessibility: automated contrast check only; manual screen-reader/keyboard audit not done.
27. Preview/run history has no pagination beyond the latest 100 runs.
