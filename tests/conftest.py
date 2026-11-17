import re
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import ROOT, Settings
from app import users


def make_settings(tmp_path, **over):
    env = {
        "PORTAL_DB_PATH": str(tmp_path / "t.db"),
        "PORTAL_WORKFLOWS_FILE": str(ROOT / "config/workflows.yaml"),
        "PORTAL_INVENTORY_FILE": str(ROOT / "config/inventory.example.yaml"),
        "PORTAL_MAX_FAILED_ATTEMPTS": "3",
        "PORTAL_LOCKOUT_MINUTES": "15",
    }
    env.update(over)
    return Settings.from_env(env)


@pytest.fixture
def app(tmp_path):
    a = create_app(make_settings(tmp_path))
    a.state.runs.submit = a.state.runs._execute  # run synchronously in tests
    st = a.state
    with st.db.conn() as c:
        users.create_user(c, st.settings, username="alice", password="correct horse battery", role="admin",
                          created_by="t", must_change_password=False)
        users.create_user(c, st.settings, username="bob", password="staple battery horse", role="engineer",
                          created_by="t", must_change_password=False)
        users.create_user(c, st.settings, username="vera", password="viewer viewer viewer1", role="viewer",
                          created_by="t", must_change_password=False)
    return a


def client_for(app):
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def client(app):
    return client_for(app)


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client, username, password):
    page = client.get("/login")
    return client.post("/login", data={"username": username, "password": password,
                                       "csrf_token": csrf_from(page.text), "next": "/"})


def session_csrf(client, path="/"):
    return csrf_from(client.get(path).text)
