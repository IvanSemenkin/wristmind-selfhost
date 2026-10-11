"""Fixed external search endpoints; provider keys never reach chat clients."""
import base64
import xml.etree.ElementTree as ET
import httpx
from .web_search import WebSearchResult, WebSearchUnavailable, _clean_text, _is_public_http_url


async def search_external(provider, key, folder_id, query, timeout, limit):
    if not key:
        raise WebSearchUnavailable('Добавьте ключ поискового API в настройках')
    limit = max(1, min(20, limit))
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=False, trust_env=False) as client:
            if provider == 'brave':
                response = await client.get('https://api.search.brave.com/res/v1/web/search', headers={'X-Subscription-Token':key}, params={'q':query[:400], 'count':limit, 'search_lang':'ru'})
            elif provider == 'tavily':
                response = await client.post('https://api.tavily.com/search', headers={'Authorization':f'Bearer {key}'}, json={'query':query[:400], 'max_results':limit, 'search_depth':'basic', 'include_answer':False, 'include_raw_content':False})
            elif provider == 'yandex' and folder_id:
                response = await client.post('https://searchapi.api.cloud.yandex.net/v2/web/search', headers={'Authorization':f'Api-Key {key}'}, json={'folderId':folder_id, 'query':{'searchType':'SEARCH_TYPE_RU', 'queryText':query[:400], 'familyMode':'FAMILY_MODE_MODERATE'}, 'groupSpec':{'groupMode':'GROUP_MODE_FLAT', 'groupsOnPage':str(limit), 'docsInGroup':'1'}, 'responseFormat':'FORMAT_XML'})
            else:
                raise WebSearchUnavailable('Проверьте настройки поискового провайдера')
            response.raise_for_status()
            if len(response.content) > 2 * 1024**2:
                raise ValueError('Response too large')
            body = response.json()
        if provider == 'brave':
            rows = body.get('web', {}).get('results', [])
        elif provider == 'tavily':
            rows = body.get('results', [])
        else:
            xml = base64.b64decode(body.get('rawData', ''), validate=True)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise ValueError('Unsafe XML')
            root = ET.fromstring(xml)
            if root.find('.//error') is not None:
                raise ValueError('Search error')
            rows = [{'title': ''.join(doc.find('title').itertext()) if doc.find('title') is not None else '', 'url':doc.findtext('url', ''), 'content':' '.join(''.join(p.itertext()) for p in doc.findall('.//passage'))} for doc in root.findall('.//doc')]
        if not isinstance(rows, list): raise ValueError('Invalid search results')
        results = []
        for row in rows:
            if not isinstance(row, dict): continue
            url = str(row.get('url') or '').strip()
            if not _is_public_http_url(url): continue
            title = _clean_text(row.get('title'), 180)
            snippet = _clean_text(row.get('content') or row.get('description'), 700)
            if title or snippet: results.append(WebSearchResult(title or url, url, snippet))
            if len(results) >= limit: break
        return results
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, ET.ParseError):
        raise WebSearchUnavailable('Поисковый API недоступен. Проверьте ключ, права, баланс и ID каталога.') from None
