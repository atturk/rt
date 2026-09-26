"""
rt.api.spa
La SPA (frontend/, fase F) servita dalla stessa origine dell'API: niente CORS in produzione.

- GET /login?code=... consuma il link monouso creato da 'rt web --spa' o da
  POST /api/v1/auth/login-link, apre la sessione con cookie e reindirizza a /.
- Ogni altro GET fuori da /api, /docs e /openapi.json restituisce un file della build o, per
  le rotte della SPA, index.html (il router lato client decide cosa mostrare).

La build si cerca in RT_SPA_DIR, poi in rt/spa (release) e in frontend/dist (sviluppo).
"""
import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from rt.api.errors import error_response

SPA_DIR_ENV = "RT_SPA_DIR"
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
RESERVED_PREFIXES = ("api/", "docs", "openapi.json")


def find_spa_dir() -> Optional[str]:
    candidates = [os.environ.get(SPA_DIR_ENV, "").strip(),
                  os.path.join(_PACKAGE_DIR, "spa"),
                  os.path.join(_PROJECT_ROOT, "frontend", "dist")]
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "index.html")):
            return os.path.abspath(candidate)
    return None


def install_spa(app: FastAPI, spa_dir: Optional[str]) -> None:
    from rt.api import auth
    from rt.api.routers.system import open_browser_session
    app.state.spa_dir = spa_dir

    def _index() -> Response:
        if not spa_dir:
            return error_response(404, "spa_not_built",
                                  "Interfaccia web non compilata: esegui 'npm run build' in frontend/ "
                                  "oppure aggiorna RT con 'rt -u'.")
        return FileResponse(os.path.join(spa_dir, "index.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/login", include_in_schema=False)
    def login(request: Request, code: str = "") -> Response:
        if not code:
            return _index()
        if not request.app.state.auth_disabled and not auth.consume_login_code(code):
            return RedirectResponse("/login?error=link", status_code=303)
        response = RedirectResponse("/", status_code=303)
        open_browser_session(request, response)
        return response

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith(RESERVED_PREFIXES):
            return error_response(404, "not_found", "Not Found")
        if spa_dir and path:
            target = os.path.realpath(os.path.join(spa_dir, path))
            if target.startswith(spa_dir + os.sep) and os.path.isfile(target):
                immutable = path.startswith("assets/")
                headers = {"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"}
                return FileResponse(target, headers=headers)
        return _index()
