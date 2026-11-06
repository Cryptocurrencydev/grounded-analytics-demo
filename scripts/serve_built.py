"""Serves the built frontend and the API from one port, for e2e runs and local previews."""
import os
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse

from grounded.main import app

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "frontend" / "browser"


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    file = (DIST / path).resolve()
    if path and file.is_file() and file.is_relative_to(DIST):
        return FileResponse(file)
    return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "4300")), log_level="warning")
