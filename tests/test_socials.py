from yabiztracker.domain.socials import extract_social_links, social_key

def test_social_extractor_covers_major_platforms():
    data={"Links":[{"href":"https://vk.com/example"},{"href":"https://t.me/example"},{"href":"https://max.ru/example"},{"href":"https://ok.ru/example"},{"href":"https://rutube.ru/channel/x"},{"href":"https://dzen.ru/x"},{"href":"https://youtube.com/@x"},{"href":"https://tenchat.ru/x"}]}
    out=extract_social_links(data)
    for k in ("vk","telegram","max","ok","rutube","dzen","youtube","tenchat"):
        assert k in out

def test_social_extractor_finds_urls_nested_in_arbitrary_yandex_payload():
    out=extract_social_links({"CompanyMetaData":{"SomeUnknownField":{"href":"https://vk.ru/x"},"Nested":["https://max.ru/x"]}})
    assert out["vk"] == ["https://vk.ru/x"]
    assert out["max"] == ["https://max.ru/x"]

def test_social_domain_classification():
    assert social_key("https://vkontakte.ru/x") is None
    assert social_key("https://www.vk.com/x") == "vk"

def test_social_finder_extracts_links_from_html(monkeypatch):
    from yabiztracker.services.social_finder import SocialFinderConfig, WebsiteSocialFinder
    class Resp:
        def __init__(self, text, url): self.text=text; self.url=url; self.encoding='utf-8'; self.apparent_encoding='utf-8'; self.headers={'Content-Type':'text/html'}
        def raise_for_status(self): pass
        def iter_content(self, n): yield self.text.encode()
        def close(self): pass
    finder=WebsiteSocialFinder(SocialFinderConfig(max_pages=2,respect_robots=False))
    html='<html><body><a href="https://vk.com/cat">VK</a><a href="https://max.ru/cat">MAX</a><a href="/contacts">Контакты</a></body></html>'
    monkeypatch.setattr(finder, '_fetch', lambda url,rp: (html,url))
    result=finder.scan('1','https://example.com')
    assert result.links['vk']==['https://vk.com/cat']
    assert result.links['max']==['https://max.ru/cat']
