from fastapi.testclient import TestClient

from app.main import app


def test_access_preview_is_404_by_default():
    http = TestClient(app)
    missing = http.get("/dev/acesso", follow_redirects=False)
    assert missing.status_code == 404
    unknown = http.get("/dev/acesso/aguardando", follow_redirects=False)
    assert unknown.status_code == 404
