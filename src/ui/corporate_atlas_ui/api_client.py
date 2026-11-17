"""HTTP-only interface used by Streamlit. No credentials or local indexes live here."""
import os
from urllib.parse import quote
import requests

from corporate_atlas.settings import SETTINGS


class APIError(RuntimeError):
    pass


class AtlasClient:
    def __init__(self, base_url=None):
        default_url = f'http://{SETTINGS.api.client_host}:{SETTINGS.api.port}'
        self.base_url = (base_url or os.getenv('ATLAS_API_URL', default_url)).rstrip('/')

    def request(self, method, path, **kwargs):
        try:
            response = requests.request(
                method,
                self.base_url + path,
                timeout=(
                    SETTINGS.http.api_client_connect_timeout_seconds,
                    SETTINGS.http.api_client_read_timeout_seconds,
                ),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise APIError(
                'Cannot reach the Corporate Atlas backend. Start it with: '
                f'python -m uvicorn corporate_atlas.api.app:app '
                f'--host {SETTINGS.api.host} --port {SETTINGS.api.port}'
            ) from exc
        if not response.ok:
            try:
                detail = response.json().get('detail', 'Backend request failed.')
            except ValueError:
                detail = 'Backend request failed.'
            if isinstance(detail, list):
                detail = '; '.join(error.get('msg', 'Invalid input') for error in detail)
            raise APIError(str(detail))
        try:
            return response.json()
        except ValueError as exc:
            raise APIError('The backend returned an invalid response.') from exc

    def start(self, data):
        payload = dict(data)
        action = payload.pop('action')
        path = {'prepare': '/prepare', 'query': '/query', 'delete_filings': '/filings/delete'}.get(action)
        if path is None:
            raise APIError('Unsupported backend action.')
        return self.request('POST', path, json=payload)

    def snapshot(self):
        return self.request('GET', '/jobs/current')['job']

    def stop(self, job_id):
        return self.request('POST', '/jobs/' + quote(job_id, safe='') + '/cancel')

    def inventory(self):
        return self.request('GET', '/status')['inventory']

    def filings(self):
        return self.request('GET', '/filings')['filings']

    def company_label(self, ticker):
        return self.request('GET', '/companies/' + quote(ticker, safe='') + '/label')['label']

    def usage(self):
        columns = ['operation', 'input_tokens', 'output_tokens', 'events', 'estimated_events']
        return [[row[column] for column in columns] for row in self.request('GET', '/usage')['rows']]
