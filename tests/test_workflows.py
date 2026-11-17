import json

import pytest
import yaml

from app import workflows as wfm
from app.inventory import Device, Inventory
from app.settings import ROOT
from conftest import client_for, csrf_from, login, session_csrf

PLATFORMS = {"ise", "sda", "aci", "nxos", "catalyst", "splunk", "esxi"}
INV = Inventory([Device("nxos-lab-1", "nxos", "192.0.2.13", "nxos-lab")])


def catalog():
    return wfm.load(ROOT / "config/workflows.yaml")


def test_every_platform_has_a_sample_workflow():
    c = catalog()
    assert set(c.platforms) == PLATFORMS
    for p in PLATFORMS:
        assert c.for_platform(p), p
        assert all(w.assumption for w in c.for_platform(p))


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
    attempt(lambda d: d["workflows"][3].update(platform="nope"))


def test_templates_do_not_allow_attribute_access():
    assert wfm.render("{a.__class__} {a}", {"a": "x"}) == "{a.__class__} x"


# ------------------------------------------------------------------ end-to-end flow

FORM = {"device": "nxos-lab-1", "vlan_id": "100", "vlan_name": "users"}


def test_preview_then_confirm_flow(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    page = "/p/nxos/nxos-create-vlan"
    assert "Preview changes" in c.get(page).text
    # invalid input re-renders with errors, creates no run
    r = c.post(page + "/preview", data={**FORM, "vlan_id": "9999", "csrf_token": session_csrf(c, page)})
    assert r.status_code == 400 and "Must be at most 3967." in r.text
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
    assert "Confirm (simulate)" in html and "Create VLAN 100" in html

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
        assert row["status"] == "succeeded" and "no changes were sent" in row["result_summary"]
        assert any("DRY-RUN" in r[0] for r in db.execute("SELECT message FROM run_log WHERE run_id=?", (run_id,)))
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
    assert "read-only" in c.get(page).text
    assert c.post(page + "/preview", data={**FORM, "csrf_token": session_csrf(c, "/")}).status_code == 403


def test_live_mode_refuses_todo_steps(tmp_path):
    from conftest import make_settings
    from app.main import create_app
    from app import users
    a = create_app(make_settings(tmp_path, PORTAL_EXECUTION_MODE="live"))
    a.state.runs.submit = a.state.runs._execute
    with a.state.db.conn() as db:
        users.create_user(db, a.state.settings, username="bob", password="staple battery horse",
                          role="engineer", created_by="t", must_change_password=False)
    c = client_for(a)
    login(c, "bob", "staple battery horse")
    page = "/p/nxos/nxos-create-vlan"
    run_id = c.post(page + "/preview", data={**FORM, "csrf_token": session_csrf(c, page)}).headers["location"].rsplit("/", 1)[1]
    c.post(f"/runs/{run_id}/confirm", data={"csrf_token": session_csrf(c)})
    with a.state.db.conn() as db:
        row = db.execute("SELECT status, result_summary FROM runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "failed" and "TODO" in row["result_summary"]


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


def test_dashboard_has_one_tile_per_platform(app):
    c = client_for(app)
    login(c, "alice", "correct horse battery")
    html = c.get("/").text
    assert html.count('class="tile"') == 7
    for name in ("Cisco ISE", "Cisco SDA", "Cisco ACI", "NX-OS", "Catalyst switches", "Splunk Enterprise Security", "ESXi"):
        assert name in html


def test_security_headers(app):
    r = client_for(app).get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
