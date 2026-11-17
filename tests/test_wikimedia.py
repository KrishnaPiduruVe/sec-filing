from unittest.mock import Mock

from corporate_atlas.services import wikimedia


def test_profile_prefers_legal_name_and_skips_disambiguation(monkeypatch):
    fruit = {'title': 'Apple', 'extract': 'A fruit', 'fullurl': 'https://en.wikipedia.org/wiki/Apple'}
    company = {'title': 'Apple Inc.', 'extract': 'A company', 'fullurl': 'https://en.wikipedia.org/wiki/Apple_Inc.'}
    disambiguation = {**company, 'pageprops': {'disambiguation': ''}}
    response = Mock()
    response.json.return_value = {'query': {'pages': [fruit, company, disambiguation]}}
    get = Mock(return_value=response)
    monkeypatch.setattr(wikimedia.requests, 'get', get)
    monkeypatch.setattr(wikimedia, 'sec_user_agent', lambda: 'Test tester@company.org')

    assert wikimedia.fetch_profile('APPLE INC') == company
    assert get.call_args.kwargs['params']['gsrsearch'] == 'intitle:"apple"'


def test_profile_checks_short_titles_for_company_context(monkeypatch):
    nvidia = {
        'title': 'Nvidia',
        'extract': 'Nvidia Corporation is an American technology company.',
        'fullurl': 'https://en.wikipedia.org/wiki/Nvidia',
    }
    response = Mock()
    response.json.return_value = {'query': {'pages': [nvidia]}}
    monkeypatch.setattr(wikimedia.requests, 'get', Mock(return_value=response))
    monkeypatch.setattr(wikimedia, 'sec_user_agent', lambda: 'Test tester@company.org')

    assert wikimedia.fetch_profile('NVIDIA CORP') == nvidia
    nvidia['extract'] = 'Nvidia is a fictional character.'
    assert wikimedia.fetch_profile('NVIDIA CORP') is None
