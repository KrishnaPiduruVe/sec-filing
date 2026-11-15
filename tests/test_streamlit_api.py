"""Exercise Streamlit through the HTTP adapter and in-process FastAPI server."""
import sys
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from corporate_atlas.api.app import create_app, JobService


class StreamlitAPITests(unittest.TestCase):
    def test_usage_and_query_flow_through_backend(self):
        with TestClient(create_app(JobService()), base_url='http://127.0.0.1:8000') as api:
            def transport(method, url, **kwargs):
                kwargs.pop('timeout', None)
                received = api.request(method, url, **kwargs)
                response = requests.Response()
                response.status_code = received.status_code
                response._content = received.content
                return response
            with patch('corporate_atlas_ui.api_client.requests.request', side_effect=transport), patch('corporate_atlas.api.app.usage_summary', return_value=[('answer', 100, 20, 1, 0)]):
                app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'src/ui/corporate_atlas_ui/app.py', default_timeout=30).run()
                self.assertFalse(app.exception)
                next(b for b in app.button if b.label == 'View token usage').click().run()
                table = next(e for e in app.expander if e.label == 'Usage').dataframe[0].value
                self.assertEqual(table.iloc[0]['Input tokens'], 100)
                app.text_area[0].set_value('What are the risks?')
                with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'print("Answer via FastAPI")']):
                    next(b for b in app.button if b.label == 'Explore insights').click().run()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if api.get('/jobs/current').json()['job']['status'] == 'completed':
                            break
                        time.sleep(.01)
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertTrue(any('Answer via FastAPI' in m.value for m in app.markdown))

    def test_unavailable_backend_shows_instructions(self):
        with patch('corporate_atlas_ui.api_client.requests.request', side_effect=requests.ConnectionError):
            app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'src/ui/corporate_atlas_ui/app.py', default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(any('uvicorn corporate_atlas.api.app:app' in e.value for e in app.error))


if __name__ == '__main__':
    unittest.main()
