"""Serve the compiled React interface from the same origin as the API."""
import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from corporate_atlas.paths import PROJECT_ROOT


def mount_frontend(app, directory=None):
    ui = Path(directory or os.getenv('ATLAS_UI_DIST', str(PROJECT_ROOT / 'src/ui/dist'))).resolve()
    app.mount('/assets', StaticFiles(directory=str(ui / 'assets'), check_dir=False), name='react-assets')

    @app.get('/ui-health', include_in_schema=False)
    def ui_health():
        if not (ui / 'index.html').is_file():
            raise HTTPException(503, 'React build is missing. Run npm ci and npm run build in src/ui.')
        return {'application': 'Corporate Atlas', 'frontend': 'react'}

    @app.get('/', include_in_schema=False)
    def index():
        if not (ui / 'index.html').is_file():
            raise HTTPException(503, 'React build is missing. Run npm ci and npm run build in src/ui.')
        return FileResponse(ui / 'index.html', headers={'Cache-Control': 'no-cache'})

    @app.get('/capgemini-icon.png', include_in_schema=False)
    def icon():
        path = ui / 'capgemini-icon.png'
        if not path.is_file():
            raise HTTPException(404, 'Icon not found.')
        return FileResponse(path)
