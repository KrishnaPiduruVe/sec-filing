"""Start the local FastAPI backend and bundled React application."""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path

import requests

from corporate_atlas.paths import PROJECT_ROOT
from corporate_atlas.settings import SETTINGS

ROOT = PROJECT_ROOT


def wait_for_backend(
    url,
    process=None,
    timeout=SETTINGS.launcher.startup_timeout_seconds,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError('FastAPI exited during startup. See its terminal output above.')
        try:
            response = requests.get(
                url + '/health',
                timeout=SETTINGS.launcher.readiness_request_timeout_seconds,
            )
            if response.ok and response.json().get('application') == 'Corporate Atlas':
                return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(SETTINGS.launcher.poll_interval_seconds)
    raise RuntimeError('Corporate Atlas did not become ready. Check the port and terminal output.')


def port_in_use(port, host=SETTINGS.api.host):
    try:
        with socket.create_connection(
            (host, port),
            timeout=SETTINGS.launcher.readiness_request_timeout_seconds,
        ):
            return True
    except OSError:
        return False


def already_running(url):
    try:
        backend = requests.get(
            url + '/health',
            timeout=SETTINGS.launcher.existing_service_timeout_seconds,
        )
        frontend = requests.get(
            url,
            timeout=SETTINGS.launcher.existing_service_timeout_seconds,
        )
        return (backend.ok and backend.json().get('application') == 'Corporate Atlas'
                and frontend.ok and 'text/html' in frontend.headers.get('content-type', ''))
    except (requests.RequestException, ValueError):
        return False


def wait_for_frontend(
    url,
    backend,
    timeout=SETTINGS.launcher.frontend_timeout_seconds,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if backend.poll() is not None:
            raise RuntimeError('FastAPI exited during startup. See its terminal output above.')
        try:
            response = requests.get(
                url,
                timeout=SETTINGS.launcher.readiness_request_timeout_seconds,
            )
            if response.ok and 'text/html' in response.headers.get('content-type', ''):
                return
        except requests.RequestException:
            pass
        time.sleep(SETTINGS.launcher.poll_interval_seconds)
    raise RuntimeError('React UI did not become ready. Build the frontend and check the terminal output.')


def shutdown(process, graceful=False):
    if process is None or process.poll() is not None:
        return
    if graceful and os.name != 'nt':
        process.send_signal(signal.SIGINT)
    else:
        process.terminate()
    try:
        process.wait(
            timeout=(
                SETTINGS.launcher.graceful_shutdown_timeout_seconds
                if graceful
                else SETTINGS.launcher.forced_shutdown_timeout_seconds
            )
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--host',
        default=SETTINGS.api.host,
        help='Local application bind host.',
    )
    parser.add_argument(
        '--port',
        '--ui-port',
        '--api-port',
        dest='port',
        type=int,
        default=SETTINGS.api.port,
        help='Local application and API port.',
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Choose a port between 1 and 65535.')

    url = f'http://{args.host}:{args.port}'
    frontend_index = Path(
        str(
            files('corporate_atlas_ui')
            / SETTINGS.paths.frontend_static_dir
            / 'index.html'
        )
    )
    if port_in_use(args.port, args.host):
        if already_running(url):
            print(f'Corporate Atlas is already running.\nOpen {url}\nAPI documentation: {url}/docs', flush=True)
            return
        parser.exit(1, f'Port {args.port} is already in use. Stop the existing service or choose another port with --port.\n')
    if not frontend_index.is_file():
        parser.exit(1, 'React frontend build not found. Run `npm ci` and `npm run build` in the frontend folder.\n')

    backend = None
    try:
        backend = subprocess.Popen(
            [
                sys.executable,
                '-m',
                'uvicorn',
                'corporate_atlas.api.app:app',
                '--host',
                args.host,
                '--port',
                str(args.port),
                '--workers',
                '1',
            ],
            cwd=ROOT,
        )
        wait_for_backend(url, backend)
        wait_for_frontend(url, backend)
        print(f'Corporate Atlas: {url}\nAPI documentation: {url}/docs\nCtrl+C stops the service.', flush=True)
        while backend.poll() is None:
            time.sleep(SETTINGS.launcher.monitor_interval_seconds)
        if backend.returncode:
            raise RuntimeError('FastAPI stopped unexpectedly. See its output above.')
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(f'Unable to run Corporate Atlas: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        shutdown(backend, graceful=True)


if __name__ == '__main__':
    main()
