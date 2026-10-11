import base64
import json
from unittest.mock import patch
import httpx
import pytest
from wristmind_server.search_providers import search_external
from wristmind_server.web_search import WebSearchUnavailable

@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['yandex','brave','tavily'])
async def test_external_search_uses_fixed_endpoint_and_normalizes(provider):
    seen=[]
    def handler(request):
        seen.append(request)
        row={'title':'Example','url':'https://example.org/article','content':'Useful facts'}
        if provider=='yandex':
            xml=b'<yandexsearch><response><results><grouping><group><doc><url>https://example.org/article</url><title>Example</title><passages><passage>Useful facts</passage></passages></doc></group></grouping></results></response></yandexsearch>'
            return httpx.Response(200,json={'rawData':base64.b64encode(xml).decode()})
        return httpx.Response(200,json={'web':{'results':[row]}} if provider=='brave' else {'results':[row]})
    original=httpx.AsyncClient
    with patch('wristmind_server.search_providers.httpx.AsyncClient',side_effect=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
        rows=await search_external(provider,'test-search-secret','folder', 'test query',10,3)
    assert rows[0].snippet=='Useful facts'
    assert str(seen[0].url).startswith('https://')
    assert 'test-search-secret' not in str(seen[0].url)
    assert seen[0].headers.get('Authorization') or seen[0].headers.get('X-Subscription-Token')
    assert rows[0].url=='https://example.org/article'

@pytest.mark.asyncio
async def test_yandex_rejects_unsafe_xml_and_redacts_error():
    original=httpx.AsyncClient
    def handler(request):
        return httpx.Response(200,json={'rawData':base64.b64encode(b'<!DOCTYPE x [<!ENTITY a "bad">]><x/>').decode()})
    with patch('wristmind_server.search_providers.httpx.AsyncClient',side_effect=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
        with pytest.raises(WebSearchUnavailable) as error:
            await search_external('yandex','private-search-secret','folder','q',10,3)
    assert 'private-search-secret' not in str(error.value)
