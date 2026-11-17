"""Check same-origin React asset serving and answer formatting without provider calls."""
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from corporate_atlas.api.app import create_app, JobService, job_response


class ReactFrontendTests(unittest.TestCase):
    def test_react_index_assets_icon_and_health(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'assets').mkdir()
            (root/'index.html').write_text('<html><title>Corporate Atlas</title><div id="root"></div></html>')
            (root/'assets/app.js').write_text('console.log("react")')
            (root/'capgemini-icon.png').write_bytes(b'icon-fixture')
            with TestClient(create_app(JobService(), ui_dir=root),base_url='http://127.0.0.1:8501') as client:
                self.assertEqual(client.get('/ui-health').json()['frontend'],'react')
                self.assertIn('Corporate Atlas',client.get('/').text)
                self.assertEqual(client.get('/assets/app.js').status_code,200)
                self.assertEqual(client.get('/capgemini-icon.png').status_code,200)
                self.assertEqual(client.get('/health').status_code,200)
                self.assertEqual(client.get('/docs').status_code,200)
                self.assertEqual(client.get('/assets/../../.env').status_code,404)

    def test_missing_build_has_actionable_error_and_api_still_works(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(JobService(),ui_dir=folder),base_url='http://127.0.0.1:8501') as client:
                self.assertEqual(client.get('/').status_code,503)
                self.assertIn('npm',client.get('/').json()['detail'])
                self.assertEqual(client.get('/health').status_code,200)

    def test_answers_expose_text_without_provider_metadata(self):
        job={'action':'query','status':'completed','output':"[{'type':'text','text':'Revenue was $25 million.','extras':{'signature':'hidden'}}]"}
        result=job_response(job)
        self.assertEqual(result['answer'],'Revenue was $25 million.')
        self.assertEqual(result['output'],job['output'])


if __name__=='__main__':
    unittest.main()
