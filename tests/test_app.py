from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_search_api_uses_tvmaze():
    fake = [
        {
            "tvmaze_id": 169,
            "name": "Breaking Bad",
            "premiered": "2008-01-20",
            "status": "Ended",
            "image_url": "https://example.com/bb.jpg",
            "summary": "Um professor de química.",
        }
    ]
    with patch("app.main.tvmaze.search_shows", return_value=fake):
        response = client.get("/api/shows/search", params={"q": "breaking"})
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Breaking Bad"


def test_register_and_create_club():
    email = "amigos@example.com"
    client.post("/register", data={"name": "Marcela", "email": email, "password": "segredo"})
    response = client.post("/clubs", data={"name": "Noite de série"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/clubs/")
