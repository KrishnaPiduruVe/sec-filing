import unittest
from unittest.mock import patch
import requests
from corporate_atlas_ui.api_client import AtlasClient, APIError


class ClientTests(unittest.TestCase):
    def test_request_failure_has_startup_instructions(self):
        with patch('corporate_atlas_ui.api_client.requests.request', side_effect=requests.ConnectionError()):
            with self.assertRaisesRegex(APIError, 'uvicorn corporate_atlas.api.app:app'):
                AtlasClient().snapshot()

    def test_backend_validation_is_readable(self):
        response = requests.Response()
        response.status_code = 422
        response._content = b'{"detail":[{"msg":"Select a valid ticker"}]}'
        with patch('corporate_atlas_ui.api_client.requests.request', return_value=response):
            with self.assertRaisesRegex(APIError, 'Select a valid ticker'):
                AtlasClient().start({'action': 'prepare', 'tickers': ''})

    def test_start_routes_to_typed_endpoints(self):
        client = AtlasClient()
        with patch.object(client, 'request', return_value={'id': 'job'}) as request:
            client.start({'action': 'query', 'question': 'Risk?'})
            request.assert_called_once_with('POST', '/query', json={'question': 'Risk?'})


if __name__ == '__main__':
    unittest.main()
