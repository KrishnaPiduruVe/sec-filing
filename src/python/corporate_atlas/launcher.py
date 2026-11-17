"""Start Corporate Atlas: FastAPI serves the API and compiled React UI together."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import requests
from corporate_atlas.paths import PROJECT_ROOT

ROOT = PROJECT_ROOT


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(.3)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def already_running(url):
    try:
        backend = requests.get(url + '/health', timeout=2)
        frontend = requests.get(url + '/ui-health', timeout=2)
        return (backend.ok and backend.json().get('application') == 'Corporate Atlas'
                and frontend.ok and frontend.json().get('frontend') == 'react')
    except (requests.RequestException, ValueError):
        return False


def wait_for_backend(url, process=None, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError('The server exited during startup. Check its terminal output.')
        if already_running(url):
            return
        time.sleep(.2)
    raise RuntimeError('Corporate Atlas did not become ready. Check the React build and terminal output.')


def shutdown(process):
    if process is None or process.poll() is not None:
        return
    if os.name != 'nt':
        process.send_signal(signal.SIGINT)
    else:
        process.terminate()
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', '--api-port', '--ui-port', dest='port', type=int, default=8501,
                        help='Port for both the React interface and API (default: 8501)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Choose a port between 1 and 65535.')
    url = f'http://127.0.0.1:{args.port}'
    if port_in_use(args.port):
        if already_running(url):
            print(f'Corporate Atlas is already running.\nOpen {url}\nAPI documentation: {url}/docs', flush=True)
            return
        parser.exit(1, f'Port {args.port} is already in use. Stop the old server or run:\npython run_app.py --port {args.port + 1 if args.port < 65535 else 8502}\n')
    ui = Path(os.getenv('ATLAS_UI_DIST', str(ROOT / 'src/ui/dist')))
    if not (ui / 'index.html').is_file():
        parser.exit(1, 'React build is missing. With Node.js installed, run:\nnpm --prefix src/ui ci\nnpm --prefix src/ui run build\nThen run python run_app.py again.\n')
    server = None
    try:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'corporate_atlas.api.app:app',
                                   '--host', '127.0.0.1', '--port', str(args.port), '--workers', '1'], cwd=ROOT)
        wait_for_backend(url, server)
        print(f'Corporate Atlas: {url}\nAPI documentation: {url}/docs\nCtrl+C stops the application.', flush=True)
        server.wait()
        if server.returncode:
            raise RuntimeError('The server stopped unexpectedly. See its output above.')
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(f'Unable to run Corporate Atlas: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        shutdown(server)


if __name__ == '__main__':
    main()
