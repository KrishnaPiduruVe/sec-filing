"""Start Corporate Atlas's FastAPI backend and Streamlit UI together."""
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
from importlib.resources import files

ROOT = PROJECT_ROOT


def wait_for_backend(url, process=None, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError('FastAPI exited during startup. See its terminal output above.')
        try:
            response = requests.get(url + '/health', timeout=1)
            if response.ok and response.json().get('application') == 'Corporate Atlas':
                return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(.2)
    raise RuntimeError('FastAPI did not become ready. Check the port and terminal output.')


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(.3)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def already_running(api_url, ui_url):
    try:
        backend = requests.get(api_url + '/health', timeout=2)
        frontend = requests.get(ui_url + '/_stcore/health', timeout=2)
        return (backend.ok and backend.json().get('application') == 'Corporate Atlas'
                and frontend.ok and frontend.text.strip() == 'ok')
    except (requests.RequestException, ValueError):
        return False


def wait_for_frontend(url, frontend, backend, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frontend.poll() is not None or backend.poll() is not None:
            raise RuntimeError('A service exited during startup. Check its output above and port availability.')
        try:
            response = requests.get(url + '/_stcore/health', timeout=1)
            if response.ok and response.text.strip() == 'ok':
                return
        except requests.RequestException:
            pass
        time.sleep(.2)
    raise RuntimeError('Streamlit did not become ready. Check its terminal output.')


def shutdown(process, graceful=False):
    if process is None or process.poll() is not None:
        return
    if graceful and os.name != 'nt':
        process.send_signal(signal.SIGINT)
    else:
        process.terminate()
    try:
        process.wait(timeout=45 if graceful else 10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--ui-port', type=int, default=8501)
    args = parser.parse_args()
    if not 1 <= args.api_port <= 65535 or not 1 <= args.ui_port <= 65535 or args.api_port == args.ui_port:
        parser.error('Choose two distinct ports between 1 and 65535.')
    url = f'http://127.0.0.1:{args.api_port}'
    ui_url = f'http://127.0.0.1:{args.ui_port}'
    occupied = [port for port in (args.api_port, args.ui_port) if port_in_use(port)]
    if occupied:
        if len(occupied) == 2 and already_running(url, ui_url):
            print(f'Corporate Atlas is already running.\nOpen {ui_url}\nAPI documentation: {url}/docs', flush=True)
            return
        parser.exit(1, 'Port(s) already in use: ' + ', '.join(map(str, occupied)) +
                    '. Stop the existing services or choose unused ports, for example:\n'
                    'python run_app.py --api-port 8001 --ui-port 8502\n')
    backend = frontend = None
    try:
        backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'corporate_atlas.api.app:app',
                                    '--host', '127.0.0.1', '--port', str(args.api_port), '--workers', '1'], cwd=ROOT)
        wait_for_backend(url, backend)
        env = {**os.environ, 'ATLAS_API_URL': url}
        frontend = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(files('corporate_atlas_ui') / 'app.py'),
                                     '--server.address', '127.0.0.1', '--server.port', str(args.ui_port),
                                     '--server.headless', 'true', '--browser.gatherUsageStats', 'false'], cwd=ROOT, env=env)
        wait_for_frontend(ui_url, frontend, backend)
        print(f'Corporate Atlas: http://127.0.0.1:{args.ui_port}\nAPI documentation: {url}/docs\nCtrl+C stops both services.', flush=True)
        while frontend.poll() is None and backend.poll() is None:
            time.sleep(.25)
        if backend.poll() not in (None, 0):
            raise RuntimeError('FastAPI stopped unexpectedly. See its output above.')
        if frontend.poll() not in (None, 0):
            raise RuntimeError('Streamlit stopped unexpectedly. See its output above.')
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(f'Unable to run Corporate Atlas: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        shutdown(frontend)
        shutdown(backend, graceful=True)


if __name__ == '__main__':
    main()
