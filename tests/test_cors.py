from fastapi.testclient import TestClient

from main import create_app

PAGES = "https://team.example.io"
PREFLIGHT = {"Origin": PAGES, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}


def test_a_listed_origin_may_call_the_chat_api_from_a_browser():
    app = create_app(cors_origins=[PAGES])

    response = TestClient(app).options("/chat", headers=PREFLIGHT)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PAGES


def test_an_unlisted_origin_is_refused():
    app = create_app(cors_origins=[PAGES])

    response = TestClient(app).options("/chat", headers={**PREFLIGHT, "Origin": "https://elsewhere.example"})

    assert "access-control-allow-origin" not in response.headers


def test_without_configured_origins_no_cross_origin_access_is_granted():
    response = TestClient(create_app()).options("/chat", headers=PREFLIGHT)

    assert "access-control-allow-origin" not in response.headers
