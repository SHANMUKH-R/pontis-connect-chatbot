from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

# The static site sits at the repository root, next to main.py.
SITE_DIR = Path(__file__).resolve().parents[4]

router = APIRouter(tags=["site"], include_in_schema=False)


# Each file is named here on purpose. Mounting the whole root would also serve .env and data/.
@router.get("/")
def index() -> FileResponse:
    return FileResponse(SITE_DIR / "index.html", media_type="text/html")


@router.get("/app.js")
def script() -> FileResponse:
    return FileResponse(SITE_DIR / "app.js", media_type="text/javascript")


@router.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(SITE_DIR / "styles.css", media_type="text/css")
