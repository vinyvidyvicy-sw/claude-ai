import json

import pytest
import yaml

from app import workflows as wfm
from app.inventory import Device, Inventory
from app.settings import ROOT
from conftest import client_for, csrf_from, login, session_csrf

PLATFORMS = {"ise", "sda", "aci", "nxos", "catalyst", "splunk", "esxi", "ekahau"}
INV = Inventory([Device("nxos-lab-1", "nxos", "192.0.2.13")])


def catalog():
    return wfm.load(ROOT / "config/workflows.yaml")


def test_every_platform_has_a_sample_workflow():
    c = catalog()
    assert set(c.platforms) == PLATFORMS
    for p in PLATFORMS - {"ekahau"}:
        assert c.for_platform(p), p
        assert all(w.assumption for w in c.for_platform(p))
    assert c.platforms["ekahau"].launcher and not c.for_platform("ekahau")


def test_param_validation():
    wf = catalog().workflows["nxos-create-vlan"]
    ok, err = wfm.validate_params(wf, {"device": "nxos-lab-1", "vlan_id": "100", "vlan_name": "users"}, INV)
    assert not err and ok["vlan_id"] == 100
    for bad in ({"device": "nope", "vlan_id": "100", "vlan_name": "x"},
                {"device": "nxos-lab-1", "vlan_id": "5000", "vlan_name": "x"},
                {"device": "nxos-lab-1", "vlan_id": "abc", "vlan_name": "x"},
                {"device": "nxos-lab-1", "vlan_id": "10", "vlan_name": "bad name;reload"},
                {"device": "nxos-lab-1", "vlan_id": "10", "vlan_name": "x\nreload"},
                {"device": "nxos-lab-1", "vlan_id": "10"}):
        _, err = wfm.validate_params(wf, bad, INV)
        assert err, bad


def test_ip_cidr_types():
    mk = lambda t: wfm.Param(name="p", label="p", type=t)
    wf = catalog().workflows["nxos-create-vlan"]
    assert wfm._validate_one(mk("ip"), "192.0.2.1", wf, INV) == "192.0.2.1"
    with pytest.raises(ValueError):
        wfm._validate_one(mk("ip"), "999.1.1.1", wf, INV)
    assert wfm._validate_one(mk("cidr"), "192.0.2.0/24", wf, INV) == "192.0.2.0/24"
    with pytest.raises(ValueError):
        wfm._validate_one(mk("cidr"), "192.0.2.5/24", wf, INV)


def _load_text(tmp_path, text):
    p = tmp_path / "w.yaml"
    p.write_text(text)
    return wfm.load(p)


def test_loader_rejects_bad_config(tmp_path):
    base = yaml.safe_load((ROOT / "config/workflows.yaml").read_text())
    wf = base["workflows"][3]

    def attempt(mutate):
        d = json.loads(json.dumps(base))
        mutate(d)
        with pytest.raises(wfm.WorkflowConfigError):
            _load_text(tmp_path, yaml.safe_dump(d))

    attempt(lambda d: d["workflows"][3]["parameters"].append({"name": "api_token", "type": "string"}))
    attempt(lambda d: d["workflows"].append(json.loads(json.dumps(wf))))  # duplicate id
    attempt(lambda d: d["workflows"][3]["plan"]["steps"][0].update(description="{missing}"))
    attempt(lambda d: d["workflows"][3]["plan"]["steps"][0].update(interface="nxos-api"))  # old key rejected
    attempt(lambda d: d["workflows"][3]["dispatch"].update(payload={"api_token": "{vlan_id}"}))
    attempt(lambda d: d["workflows"][3].update(platform="nope"))


def test_templates_do_not_allow_attribute_access():
    assert wfm.render("{a.__class__} {a}", {"a": "x"}) == "{a.__class__} x"


# ------------------------------------------------------------------ end-to-end flow

FORM = {"device": "nxos-lab-1", "vlan_id": "100", "vlan_name": "users"}


def test_preview_then_confirm_flow(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = "/p/nxos/nxos-create-vlan"
    assert "Pratinjau perubahan" in c.get(page).text
    # invalid input re-renders with errors, creates no run
    r = c.post(page + "/preview", data={**FORM, "vlan_id": "9999", "csrf_token": session_csrf(c, page)})
    assert r.status_code == 400 and "Harus maksimal 3967." in r.text
    with app.state.db.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0

    r = c.post(page + "/preview", data={**FORM, "csrf_token": session_csrf(c, page)})
    assert r.status_code == 303
    run_url = r.headers["location"]
    run_id = run_url.rsplit("/", 1)[1]
    with app.state.db.conn() as db:
        row = db.execute("SELECT status, mode FROM runs WHERE id=?", (run_id,)).fetchone()
        assert (row["status"], row["mode"]) == ("previewed", "dry_run")  # nothing runs before confirm
        assert db.execute("SELECT COUNT(*) FROM run_log WHERE run_id=?", (run_id,)).fetchone()[0] == 0
    html = c.get(run_url).text
    assert "Konfirmasi (simulasi)" in html and "Buat VLAN 100" in html
    assert "tidak mengubah perangkat" in html

    # another user cannot confirm
    other = client_for(app)
    login(other, "alice", "correct horse battery")
    r = other.post(run_url + "/confirm", data={"csrf_token": session_csrf(other)})
    assert r.status_code == 409
    with app.state.db.conn() as db:
        assert db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "previewed"

    r = c.post(run_url + "/confirm", data={"csrf_token": session_csrf(c, run_url)})
    assert r.status_code == 303
    with app.state.db.conn() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        assert row["status"] == "succeeded" and "tidak ada permintaan yang dikirim" in row["result_summary"]
        assert any("tidak ada yang dikirim" in r[0] for r in db.execute("SELECT message FROM run_log WHERE run_id=?", (run_id,)))
        acts = [r[0] for r in db.execute("SELECT action FROM audit_log WHERE target='nxos-create-vlan' ORDER BY id")]
    assert acts == ["workflow.preview", "workflow.confirm", "workflow.confirm", "workflow.run"]  # 2nd = denied attempt by another user
    # second confirm is refused
    assert c.post(run_url + "/confirm", data={"csrf_token": session_csrf(c, run_url)}).status_code == 409
    assert c.get(run_url + "/status.json").json()["status"] == "succeeded"


def test_tampered_plan_is_refused(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = "/p/nxos/nxos-create-vlan"
    r = c.post(page + "/preview", data={**FORM, "csrf_token": session_csrf(c, page)})
    run_id = r.headers["location"].rsplit("/", 1)[1]
    with app.state.db.conn() as db:
        db.execute("UPDATE runs SET params_json=? WHERE id=?", (json.dumps({"vlan_id": 1}), run_id))
    r = c.post(f"/runs/{run_id}/confirm", data={"csrf_token": session_csrf(c)})
    assert r.status_code == 409
    with app.state.db.conn() as db:
        assert db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "failed"


def test_viewer_cannot_preview(app):
    c = client_for(app)
    login(c, "vera", "viewer viewer viewer1")
    page = "/p/nxos/nxos-create-vlan"
    assert "hanya dapat melihat" in c.get(page).text
    assert c.post(page + "/preview", data={**FORM, "csrf_token": session_csrf(c, "/")}).status_code == 403


def _live_app(tmp_path, **env):
    from conftest import make_settings
    from app.main import create_app
    from app import users
    a = create_app(make_settings(tmp_path, PORTAL_EXECUTION_MODE="live", PORTAL_BACKEND_POLL_SECONDS="0", **env))
    a.state.runs.submit = a.state.runs._execute
    with a.state.db.conn() as db:
        users.create_user(db, a.state.settings, username="bob", password="staple battery horse",
                          role="engineer", created_by="t", must_change_password=False)
    c = client_for(a)
    login(c, "bob", "staple battery horse")
    return a, c


def _run_vlan(c):
    page = "/p/nxos/nxos-create-vlan"
    run_id = c.post(page + "/preview", data={**FORM, "csrf_token": session_csrf(c, page)}).headers["location"].rsplit("/", 1)[1]
    c.post(f"/runs/{run_id}/confirm", data={"csrf_token": session_csrf(c)})
    return run_id


def _row(a, run_id):
    with a.state.db.conn() as db:
        return db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def test_live_mode_refuses_todo_dispatch(tmp_path):
    a, c = _live_app(tmp_path)
    row = _row(a, _run_vlan(c))
    assert row["status"] == "failed" and "TODO" in row["result_summary"]


def test_live_mode_hands_off_to_backend_and_mirrors_status(tmp_path, monkeypatch):
    from app import runner, workflows as wfm
    from app.runner import JobStatus
    calls = {"polls": 0, "submitted": None}

    class Fake:
        def submit(self, job):
            calls["submitted"] = job
            return "job-42"

        def poll(self, job_id):
            calls["polls"] += 1
            if calls["polls"] < 2:
                return JobStatus("running", ["started"])
            return JobStatus("succeeded", ["started", "vlan created token=abc123"], "done")

    a, c = _live_app(tmp_path)
    runner.register_backend("fake", Fake())
    try:
        # point the workflow at the fake backend
        wf = a.state.catalog.workflows["nxos-create-vlan"]
        a.state.catalog.workflows["nxos-create-vlan"] = wfm.replace_dispatch(wf, backend="fake", job="create_vlan")
        run_id = _run_vlan(c)
    finally:
        runner.BACKENDS.pop("fake", None)
    row = _row(a, run_id)
    assert row["status"] == "succeeded" and row["backend_job_id"] == "job-42"
    job = calls["submitted"]
    assert job["backend_job"] == "create_vlan" and job["payload"]["vlan_id"] == 100 and job["run_id"] == run_id
    with a.state.db.conn() as db:
        msgs = " | ".join(r[0] for r in db.execute("SELECT message FROM run_log WHERE run_id=?", (run_id,)))
    assert "[backend] started" in msgs and "vlan created" in msgs and "abc123" not in msgs  # secret-like text scrubbed


def test_live_mode_backend_failure_and_timeout(tmp_path):
    from app import runner, workflows as wfm
    from app.runner import JobStatus

    class Failing:
        def submit(self, job): return "j1"
        def poll(self, job_id): return JobStatus("failed", ["boom"], "backend said no")

    class Stuck:
        def submit(self, job): return "j2"
        def poll(self, job_id): return JobStatus("running", [])

    for backend, env, expect in ((Failing(), {}, "backend said no"),
                                 (Stuck(), {"PORTAL_BACKEND_TIMEOUT_SECONDS": "1"}, "batas waktu")):
        a, c = _live_app(tmp_path / expect[:4], **env)
        runner.register_backend("fake", backend)
        try:
            wf = a.state.catalog.workflows["nxos-create-vlan"]
            a.state.catalog.workflows["nxos-create-vlan"] = wfm.replace_dispatch(wf, backend="fake", job="x")
            row = _row(a, _run_vlan(c))
        finally:
            runner.BACKENDS.pop("fake", None)
        assert row["status"] == "failed" and expect in row["result_summary"]


def test_portal_holds_no_device_credentials():
    import importlib.util
    assert importlib.util.find_spec("app.credentials") is None


def test_audit_never_contains_secrets(app, tmp_path):
    from app import audit
    with app.state.db.conn() as db:
        audit.record(db, actor="x", action="t", result="ok",
                     params={"password": "hunter2", "api_token": "abc", "vlan": 1},
                     detail="login password=hunter2 failed")
        row = db.execute("SELECT params_json, detail FROM audit_log WHERE action='t'").fetchone()
    assert "hunter2" not in row[0] + row[1] and "abc" not in row[0]
    c = client_for(app)
    login(c, "alice", "correct horse battery")
    assert "correct horse battery" not in c.get("/admin/audit").text
    assert "correct horse battery" not in open(app.state.settings.db_path, "rb").read().decode("latin1")


def test_ekahau_launcher_tile(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    # not configured: tile leads to a TODO page, launch does not leave the portal
    assert c.get("/launch/ekahau").headers["location"] == "/p/ekahau"
    assert "belum dikonfigurasi" in c.get("/p/ekahau").text
    # configured: tile opens the launcher in a new tab and the launch is audited
    app.state.inventory._launchers["ekahau"] = "https://ekahau.example.invalid/design"
    html = c.get("/").text
    assert 'href="/launch/ekahau"' in html and 'target="_blank"' in html and "noopener" in html
    r = c.get("/launch/ekahau")
    assert r.status_code == 303 and r.headers["location"] == "https://ekahau.example.invalid/design"
    with app.state.db.conn() as db:
        row = db.execute("SELECT actor, target, result FROM audit_log WHERE action='platform.launch'").fetchone()
    assert tuple(row) == ("bob", "ekahau", "success")
    assert c.get("/launch/ise").status_code == 404  # only launcher platforms


def test_launcher_url_must_be_https(tmp_path):
    from app import inventory
    p = tmp_path / "inv.yaml"
    p.write_text("devices: []\nlaunchers:\n  ekahau:\n    url: http://insecure.example\n")
    import pytest
    with pytest.raises(inventory.InventoryError):
        inventory.load(p)


def test_dashboard_has_one_tile_per_platform(app):
    c = client_for(app)
    login(c, "alice", "correct horse battery")
    html = c.get("/").text
    assert html.count('class="tile"') == 8
    assert html.count('class="icon"') == 8 and "<rect x=\"4\" y=\"4\" width=\"16\"" not in html  # every tile has a real icon, none fell back to the placeholder
    for name in ("Cisco ISE", "Cisco SDA", "Cisco ACI", "NX-OS", "Catalyst switches", "Splunk Enterprise Security", "ESXi", "Ekahau Design"):
        assert name in html


def test_security_headers(app):
    r = client_for(app).get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_logos_shown_only_when_files_exist(app):
    from app import main
    assert main._find_logos() == [] or all(l["src"].startswith("/static/img/") for l in main._find_logos())
    import pathlib
    f = pathlib.Path(main.BASE / "static/img/logo-mii.svg")
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    try:
        app.state.templates.env.globals["logos"] = main._find_logos()
        html = client_for(app).get("/login").text
        assert "/static/img/logo-mii.svg" in html and "PT Mitra Integrasi Informatika" in html
    finally:
        f.unlink()


def test_ui_is_indonesian_and_has_innovation_menu(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    html = c.get("/").text
    assert '<html lang="id">' in html and "Pilih platform" in html and "Keluar" in html
    # Inovasi dropdown with both items
    assert "Inovasi" in html and "/inovasi/metrodata-ai-use-case" in html and "/inovasi/splunk-innovation" in html
    assert "Metrodata AI Use Case" in html and "Splunk Innovation" in html


def test_innovation_pages_and_launch(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = c.get("/inovasi/metrodata-ai-use-case")
    assert page.status_code == 200
    for title in ("Joint Planning Session", "Go To Market", "Document Procurement"):
        assert title in page.text
    assert page.text.count('class="icon"') == 8   # page icon + 7 cards
    for title in ("Trade Finance Document Examination", "Customer Analytics and Credit Scoring",
                  "Predictive Maintenance for Machines", "Real-time Component Inspection"):
        assert title in page.text
    assert page.text.count("badge-category") == 4 and "Banking" in page.text and "Manufacturing" in page.text
    assert "Reads every page of a trade document set, checks it against the credit terms and the bank&#39;s rules, and explains each finding." in page.text
    assert "Textract" not in page.text and "Agentic" not in page.text   # procurement text was removed on request
    # no TODO notes, no source/'Dari dokumen' messages, no repeated "opens in new tab" hints on the list
    for banned in ("TODO", "Dari dokumen", "dokumen PDF", "belum disiapkan", "Dibuka di tab baru", "Lihat penjelasan"):
        assert banned not in page.text, banned
    # cards with document text link to their page; JPS and GTM open their dashboards directly
    assert 'href="/inovasi/metrodata-ai-use-case/banking-trade-finance-document-examination"' in page.text
    assert 'href="/launch/go-to-market"' in page.text and 'href="/launch/joint-planning-session"' in page.text
    assert c.get("/launch/metrodata-ai-use-case").headers["location"] == "/inovasi/metrodata-ai-use-case"
    # each card has its own page; not configured -> TODO, launch falls back to that page
    detail = c.get("/inovasi/metrodata-ai-use-case/document-procurement").text
    assert "TODO" not in detail and "belum dikonfigurasi" not in detail and "Textract" not in detail
    assert c.get("/launch/document-procurement").headers["location"] == "/inovasi/metrodata-ai-use-case/document-procurement"
    app.state.inventory._launchers["document-procurement"] = "https://docs.example.invalid/"
    assert 'href="/launch/document-procurement"' in c.get("/inovasi/metrodata-ai-use-case").text
    r = c.get("/launch/document-procurement")
    assert r.status_code == 303 and r.headers["location"] == "https://docs.example.invalid/"
    # the two dashboards with committed default addresses open straight away
    for key, url in (("go-to-market", "https://metrodata-ai-gtm.netlify.app"),
                     ("joint-planning-session", "https://metrodata-ai-jps.netlify.app")):
        r = c.get(f"/launch/{key}")
        assert r.status_code == 303 and r.headers["location"] == url
    assert c.get("/inovasi/metrodata-ai-use-case/nope").status_code == 404
    app.state.inventory._launchers["splunk-innovation"] = "https://splunk-innovation.example.invalid/"
    page = c.get("/inovasi/splunk-innovation")
    assert 'href="/launch/splunk-innovation"' in page.text and 'target="_blank"' in page.text
    r = c.get("/launch/splunk-innovation")
    assert r.status_code == 303 and r.headers["location"] == "https://splunk-innovation.example.invalid/"
    with app.state.db.conn() as db:
        row = db.execute("SELECT actor, action, target FROM audit_log WHERE action='innovation.launch' AND target='splunk-innovation'").fetchone()
    assert tuple(row) == ("bob", "innovation.launch", "splunk-innovation")
    assert c.get("/inovasi/unknown").status_code == 404


def test_inventory_launcher_overrides_default_and_default_must_be_https(app, tmp_path):
    from app import workflows as wfm
    from app.settings import ROOT
    inv = app.state.inventory
    inv._launchers["go-to-market"] = "https://override.example.invalid/"   # as from inventory.yaml
    inv.set_default_launcher("go-to-market", "https://metrodata-ai-gtm.netlify.app")  # default must not replace it
    assert inv.launch_url("go-to-market") == "https://override.example.invalid/"
    bad = (ROOT / "config/workflows.yaml").read_text().replace("url: https://metrodata-ai-gtm.netlify.app", "url: http://insecure.example")
    p = tmp_path / "w.yaml"; p.write_text(bad)
    import pytest
    with pytest.raises(wfm.WorkflowConfigError):
        wfm.load(p)


def test_portal_title(app):
    html = client_for(app).get("/login").text
    assert "Cisco &amp; Splunk Lab Portal" in html  # autoescaped in HTML


def test_login_page_white_with_topology_left_and_rack_right(app):
    html = client_for(app).get("/login").text
    assert 'class="login-page"' in html
    # DOM (and desktop grid) order: topology, login form, rack
    i_topo, i_form, i_rack = (html.index(x) for x in ("login-topology.jpg", 'action="/login"', "login-rack.jpg"))
    assert i_topo < i_form < i_rack
    c = client_for(app)
    for f in ("login-topology.jpg", "login-rack.jpg"):
        assert c.get("/static/img/" + f).status_code == 200
    css = c.get("/static/css/app.css").text
    assert "opacity: 0.10" not in css and "background: var(--color-bg)" in css  # no faded background any more


def test_login_title_centered_bold(app):
    html = client_for(app).get("/login").text
    assert '<h1 class="login-title">MII - Hybrid AI Infrastructure Lab Topology</h1>' in html
    assert html.count('class="logos"') == 1  # logos only in the header (top-right), not repeated in the card
    css = client_for(app).get("/static/css/app.css").text
    assert ".login-title { text-align: center; font-weight: 700;" in css and "margin-left: auto" in css


def test_dashboard_wording(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    html = c.get("/").text
    assert ">Dashboard</a>" in html and "Dasbor" not in html and "dasbor" not in html


def test_device_console_link_is_audited(app):
    import dataclasses
    inv = app.state.inventory
    dev = inv.get("nxos-lab-1")
    inv._by_name["nxos-lab-1"] = dataclasses.replace(dev, console_url="https://192.0.2.13/console")
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = c.get("/p/nxos").text
    assert 'href="/console/nxos-lab-1"' in page and 'target="_blank"' in page and "noopener" in page
    r = c.get("/console/nxos-lab-1")
    assert r.status_code == 303 and r.headers["location"] == "https://192.0.2.13/console"
    with app.state.db.conn() as db:
        row = db.execute("SELECT actor, action, target FROM audit_log WHERE action='device.console_open'").fetchone()
    assert tuple(row) == ("bob", "device.console_open", "nxos-lab-1")
    assert c.get("/console/ise-lab-1").status_code == 404   # no console_url configured
    assert c.get("/console/tidak-ada").status_code == 404


def test_use_case_pages_show_pdf_text_as_is_and_unknowns_say_so(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = c.get("/inovasi/metrodata-ai-use-case/banking-trade-finance-document-examination").text
    for text in ("Owner: Trade operations, with the checkers", "Target of two minutes or less per set",
                 "Three Linux VMs on the bank&#39;s servers", "Phase 3, SIT, UAT and handover",
                 "Banking, the document examination flow", "Every decision, override and source is written to the process log",
                 "Dataiku and Amazon Bedrock, hybrid"):
        assert text in page, text
    assert "Halaman" not in page and "hal." not in page and "page 2" not in page   # page references are not shown in the UI
    for banned in ("TODO", "Dari dokumen", "apa adanya", "Judul di dokumen", "belum dikonfigurasi"):
        assert banned not in page, banned
    one_liner = "Reads every page of a trade document set, checks it against the credit terms and the bank&#39;s rules, and explains each finding."
    assert page.count(one_liner) == 1   # shown once, not repeated
    for uid in ("joint-planning-session", "go-to-market", "document-procurement"):
        p = c.get(f"/inovasi/metrodata-ai-use-case/{uid}").text
        assert "Dari dokumen" not in p and "Halaman" not in p and "TODO" not in p


def test_every_source_text_line_is_present_in_the_yaml_and_matches_the_catalog(app):
    st = app.state
    ids = {u.id for i in st.catalog.innovation.values() for u in i.use_cases}
    assert set(st.sources) <= ids and set(st.sources) == ids - {"joint-planning-session", "go-to-market", "document-procurement"}
    for cid, case in st.sources.items():
        assert case["pages"] and case["blocks"] and case["overview"]["One-line description"]


def test_slide_layouts_follow_the_pdf(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = c.get("/inovasi/metrodata-ai-use-case/banking-trade-finance-document-examination").text
    # blueprint: seven numbered sections + architecture, in the PDF's headings
    for h in ("1. Problem statement and owner", "2. High level solution", "3. Level of trust and human gates",
              "4. Data and system readiness", "High level solution, architecture", "5. Expected business impact",
              "6. Effort, duration and team", "7. Sequence and roadmap"):
        assert h in page, h
    assert page.count('class="bp-card') == 5 and page.count('class="bp-block') == 3 and page.count("arch-step") == 5
    assert "Level 2" in page and "Prepares, you decide" in page and "WHAT IT DOES" in page
    # flow: stage columns and the three lanes with numbered steps placed in columns
    assert "01</span> Receive" in page and 'aria-label="PEOPLE"' in page and 'aria-label="AI"' in page and 'aria-label="AUTOMATION"' in page
    assert 'class="step col-5"' in page and page.count('class="stepnum"') == 11
    assert page.count("lane-icon") == 3 and "arr-down" in page      # lane icons and gold arrows like the PDF
    # the list page uses the PDF's row layout with a Level pill
    lst = c.get("/inovasi/metrodata-ai-use-case").text
    assert 'class="uc-row"' in lst and lst.count('class="pill"') == 4
    assert 'data-n="1"' in page and 'src="/static/js/flow.js"' in page    # flow arrows are drawn by flow.js
    assert c.get("/static/js/flow.js").status_code == 200


def test_flow_steps_stay_inside_their_stage_columns(app):
    for cid, case in app.state.sources.items():
        for b in case["blocks"]:
            if b["kind"] == "flow":
                n = len(b["stages"])
                steps = [s for lane in b["lanes"] for s in lane["steps"]]
                assert all(1 <= s["col"] <= n for s in steps)
                assert sorted(s["n"] for s in steps) == list(range(1, len(steps) + 1))   # steps 1..N, none lost
                for lane in b["lanes"]:                                                      # one step per lane column
                    cols = [s["col"] for s in lane["steps"]]
                    assert len(cols) == len(set(cols))


def test_card_icons_match_the_pdf_and_no_page_mentions_on_the_list(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    lst = c.get("/inovasi/metrodata-ai-use-case").text
    assert "hal." not in lst and "Halaman" not in lst
    for uid, icon in (("banking-trade-finance-document-examination", "file"), ("banking-customer-analytics-credit-scoring", "people"),
                      ("manufacturing-predictive-maintenance", "tools"), ("manufacturing-realtime-component-inspection", "search")):
        uc = next(u for i in app.state.catalog.innovation.values() for u in i.use_cases if u.id == uid)
        assert uc.icon == icon
