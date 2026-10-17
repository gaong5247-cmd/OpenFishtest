"""Local admin UI must remain isolated from GitHub Pages and require API tokens."""
import importlib
import sys

from fastapi.testclient import TestClient


def test_local_admin_html_and_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "test-private-admin")
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app) as api:
        page = api.get("/admin")
        assert page.status_code == 200
        assert "Control your testing network" in page.text
        assert "test-private-admin" not in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert api.get("/admin-ui/app.js").status_code == 200
        assert api.get("/admin-ui/style.css").status_code == 200
        assert api.get("/admin-ui/secrets.txt").status_code == 404
        denied = api.get("/api/admin/workers")
        assert denied.status_code == 403
        allowed = api.get("/api/admin/workers",
            headers={"X-Admin-Token":"test-private-admin"})
        assert allowed.status_code == 200
        assert allowed.json() == []
