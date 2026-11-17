import sqlite3
from datetime import timedelta

from app import timeutil
from conftest import client_for, csrf_from, login, session_csrf


def test_hash_is_salted_argon2_and_no_plaintext(app):
    with app.state.db.conn() as c:
        hashes = [r[0] for r in c.execute("SELECT password_hash FROM users")]
    assert all(h.startswith("$argon2id$") for h in hashes)
    raw = open(app.state.settings.db_path, "rb").read()
    for pw in (b"correct horse battery", b"staple battery horse"):
        assert pw not in raw
    from app.security import hash_password
    assert hash_password("same") != hash_password("same")


def test_login_cookie_flags(client):
    r = login(client, "alice", "correct horse battery")
    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    assert "__host-portal_session=" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie


def test_requires_login_and_bad_password(client):
    assert client.get("/").status_code == 303
    r = login(client, "alice", "wrong")
    assert r.status_code == 401 and "Gagal masuk" in r.text
    assert login(client, "nobody", "x").status_code == 401


def test_lockout_after_n_failures_and_admin_unlock(app, client):
    for _ in range(3):
        login(client, "bob", "nope")
    assert login(client, "bob", "staple battery horse").status_code == 401  # locked, even if correct
    admin = client_for(app)
    login(admin, "alice", "correct horse battery")
    with app.state.db.conn() as c:
        bob_id = c.execute("SELECT id FROM users WHERE username='bob'").fetchone()[0]
        lock_events = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='auth.lockout'").fetchone()[0]
    assert lock_events == 1
    r = admin.post(f"/admin/users/{bob_id}/unlock", data={"csrf_token": session_csrf(admin, "/admin/users")})
    assert r.status_code == 303
    assert login(client, "bob", "staple battery horse").status_code == 303


def test_lockout_expires(app, client, monkeypatch):
    for _ in range(3):
        login(client, "bob", "nope")
    real = timeutil.now
    monkeypatch.setattr(timeutil, "now", lambda: real() + timedelta(minutes=16))
    assert login(client, "bob", "staple battery horse").status_code == 303


def test_idle_timeout(app, client, monkeypatch):
    login(client, "alice", "correct horse battery")
    assert client.get("/").status_code == 200
    real = timeutil.now
    monkeypatch.setattr(timeutil, "now", lambda: real() + timedelta(minutes=16))
    assert client.get("/").status_code == 303


def test_csrf_enforced(app, client):
    login(client, "alice", "correct horse battery")
    assert client.post("/logout", data={}).status_code == 403
    assert client.post("/logout", data={"csrf_token": "bad"}).status_code == 403


def test_admin_pages_forbidden_for_engineer(app):
    c = client_for(app)
    login(c, "bob", "staple battery horse")
    assert c.get("/admin/users").status_code == 403
    assert c.get("/admin/audit").status_code == 403


def test_admin_create_reset_disable(app):
    admin = client_for(app)
    login(admin, "alice", "correct horse battery")
    tok = session_csrf(admin, "/admin/users")
    r = admin.post("/admin/users", data={"username": "carol", "role": "engineer", "csrf_token": tok})
    assert r.status_code == 200 and "Kata sandi sementara" in r.text
    import re
    temp = re.search(r'class="secret"[^>]*>([^<]+)<', r.text).group(1)
    with app.state.db.conn() as c:
        row = c.execute("SELECT id, must_change_password FROM users WHERE username='carol'").fetchone()
    assert row["must_change_password"] == 1
    assert temp.encode() not in open(app.state.settings.db_path, "rb").read()

    carol = client_for(app)
    r = login(carol, "carol", temp)
    assert r.headers["location"] == "/account/password"
    assert carol.get("/").headers["location"] == "/account/password"  # forced change

    admin.post(f"/admin/users/{row['id']}/disable", data={"csrf_token": tok})
    assert login(client_for(app), "carol", temp).status_code == 401
    admin.post(f"/admin/users/{row['id']}/enable", data={"csrf_token": tok})
    r = admin.post(f"/admin/users/{row['id']}/reset", data={"csrf_token": tok})
    assert "Kata sandi sementara" in r.text


def test_cannot_disable_last_admin(app):
    admin = client_for(app)
    login(admin, "alice", "correct horse battery")
    with app.state.db.conn() as c:
        aid = c.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
    admin.post(f"/admin/users/{aid}/disable", data={"csrf_token": session_csrf(admin, "/admin/users")})
    with app.state.db.conn() as c:
        assert c.execute("SELECT is_active FROM users WHERE id=?", (aid,)).fetchone()[0] == 1


def test_audit_log_is_append_only(app):
    with app.state.db.conn() as c:
        from app import audit
        audit.record(c, actor="a", action="t", result="ok")
        try:
            c.execute("UPDATE audit_log SET actor='x'")
            c.execute("DELETE FROM audit_log")
            raise AssertionError("should not be allowed")
        except sqlite3.IntegrityError:
            pass
