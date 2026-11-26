from fastapi import FastAPI
from fastapi.testclient import TestClient

from pontis_chat.routes.site import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_home_page_and_its_assets_are_served():
    assert 'id="connect-chat"' in client().get("/").text
    assert client().get("/app.js").headers["content-type"].startswith("text/javascript")
    assert client().get("/styles.css").headers["content-type"].startswith("text/css")


def test_nothing_else_in_the_repository_root_is_served():
    for path in ("/.env", "/main.py", "/data/question_log.jsonl", "/README.md"):
        assert client().get(path).status_code == 404
