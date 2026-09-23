import unittest
from unittest.mock import patch
import requests
from yabiztracker.api.yandex import _request, YandexAPI
from yabiztracker.api.errors import ApiLimitError, ApiAuthError, ApiNetworkError, ApiInvalidResponseError

class Usage:
    def __init__(self): self.calls=[]
    def record(self,api): self.calls.append(api)

class Resp:
    def __init__(self,status=200,data=None,text='ok',headers=None): self.status_code=status; self._data=data or {}; self.text=text; self.headers=headers or {}
    def json(self): return self._data

class Session:
    def __init__(self, responses): self.responses=list(responses); self.calls=0
    def get(self,*a,**kw):
        x=self.responses.pop(0); self.calls+=1
        if isinstance(x,Exception): raise x
        return x

class ApiTests(unittest.TestCase):
    def test_success_counts_actual_request(self):
        u=Usage(); s=Session([Resp(200,{"features":[]})]); r=_request(s,'u',{},1,'search',u); self.assertEqual(r.status_code,200); self.assertEqual(u.calls,['search'])
    def test_400_does_not_retry(self):
        with patch('yabiztracker.api.yandex.time.sleep') as sleep:
            with self.assertRaises(Exception): _request(Session([Resp(400,text='bad')]),'u',{},1,'search',Usage())
            sleep.assert_not_called()

    def test_403_limit_and_auth(self):
        for text,exc in [('Limit: 100 current value: 100',ApiLimitError),('forbidden key',ApiAuthError)]:
            with self.subTest(text=text):
                with self.assertRaises(exc): _request(Session([Resp(403,text=text)]),'u',{},1,'search',Usage())
    def test_retry_429_and_5xx(self):
        with patch('yabiztracker.api.yandex.time.sleep'):
            u=Usage(); s=Session([Resp(503,text='x'),Resp(502,text='x'),Resp(200,{})]); _request(s,'u',{},1,'search',u); self.assertEqual(s.calls,3); self.assertEqual(len(u.calls),3)
    def test_network_retry(self):
        with patch('yabiztracker.api.yandex.time.sleep'):
            with self.assertRaises(ApiNetworkError): _request(Session([requests.Timeout('x')]*5),'u',{},1,'search',Usage(),retries=5)
    def test_parse_org_and_invalid_json(self):
        api=YandexAPI('','')
        f={"geometry":{"coordinates":[50.1,53.2]},"properties":{"uri":"https://yandex.ru/maps/org/x/123","name":"X","CompanyMetaData":{"id":"123","name":"X","Address":{"formatted":"A"},"Phones":[{"formatted":"1"}],"Links":[{"href":"https://vk.com/x"}]}}}
        o=api.parse_org(f); self.assertEqual(o['id'],'123'); self.assertIn('vk.com',o['social_links'])
        api.search._request=lambda *a,**k: Resp(200,text='bad')
        with self.assertRaises(ApiInvalidResponseError): api.search.search_page('x','b',0)


    def test_search_excludes_organizations_with_any_excluded_category(self):
        api=YandexAPI('','')
        class Search:
            def search_page(self,text,bbox,skip=0):
                return [
                    {"geometry":{"coordinates":[50.1,53.2]},"properties":{"name":"Allowed","CompanyMetaData":{"id":"1","Categories":[{"name":"Квесты"}]}}},
                    {"geometry":{"coordinates":[50.1,53.2]},"properties":{"name":"Mixed","CompanyMetaData":{"id":"2","Categories":[{"name":"Квесты"},{"name":"Банк"}]}}},
                ],False
        api.search=Search()
        orgs,stats=api.search_organizations([{"name":"Samara","bbox":"50,53~50.3,53.4"}],['Квесты'],excluded_categories=['Банк'])
        self.assertEqual([o['id'] for o in orgs],['1'])
        self.assertEqual(stats['excluded_by_category'],1)

    def test_parse_org_tolerates_closed_status(self):
        feature={"geometry":{"coordinates":[50.1,53.2]},"properties":{"name":"Closed","uri":"https://yandex.ru/maps/org/x/9","CompanyMetaData":{"id":"9","name":"Closed","status":"Больше не работает"}}}
        org=YandexAPI.parse_org(feature)
        self.assertEqual(org["source_status"],"closed")

    def test_exclusion_has_precedence_when_organization_matches_included_and_excluded(self):
        api=YandexAPI('','')
        class Search:
            def search_page(self,text,bbox,skip=0):
                return [{"geometry":{"coordinates":[50.1,53.2]},"properties":{"name":"Mixed","CompanyMetaData":{"id":"42","Categories":[{"name":"Развлечения"},{"name":"Центр развития ребёнка"}]}}}],False
        api.search=Search()
        orgs,stats=api.search_organizations([{"name":"Самара","bbox":"b"}],['Развлечения'],excluded_categories=['Центр развития ребёнка'])
        self.assertEqual(orgs,[])
        self.assertEqual(stats['excluded_by_category'],1)

if __name__=='__main__': unittest.main()

class ApiConcurrencyTests(unittest.TestCase):
    def test_http_session_is_thread_local(self):
        import threading
        api = YandexAPI('', '')
        barrier = threading.Barrier(8)
        sessions = []
        lock = threading.Lock()

        def worker():
            session = api.search._session()
            with lock:
                sessions.append(session)
            barrier.wait()
            barrier.wait()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(sessions), 8)
        self.assertEqual(len({id(session) for session in sessions}), 8)


def test_resolve_organization_uses_org_uri():
    from yabiztracker.api.yandex import YandexSearchClient
    c=YandexSearchClient("key")
    c.resolve_uri=lambda uri: [uri]
    assert c.resolve_organization("123") == ["ymapsbm1://org?oid=123"]
