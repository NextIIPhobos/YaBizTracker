from __future__ import annotations

import html
import logging
import re
import threading
from dataclasses import dataclass, field
from html.parser import HTMLParser
from queue import Empty, Queue
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import requests

from ..domain.socials import extract_social_links

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SocialFinderConfig:
    workers: int = 8
    max_pages: int = 5
    timeout_seconds: float = 12.0
    max_response_bytes: int = 2 * 1024 * 1024
    respect_robots: bool = True

@dataclass
class SocialScanResult:
    org_id: str
    links: dict[str, list[str]] = field(default_factory=dict)
    status: str = "not_found"
    error: str = ""
    pages: int = 0

class _SocialPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.meta = []
    def handle_starttag(self, tag, attrs):
        a = {str(k).lower(): str(v or "") for k,v in attrs}
        tag = tag.lower()
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag == "meta" and (a.get("content") or a.get("property") or a.get("name")):
            self.meta.append(a)

class WebsiteSocialFinder:
    CONTACT_HINTS = ("contact", "contacts", "контакт", "контакты", "соц", "social", "links", "ссылки", "реквизит", "about", "о компании")
    CONTACT_PATHS = ("/contacts", "/contact", "/information", "/info", "/about", "/kontakty", "/requisites")
    SKIP_EXTENSIONS = re.compile(r"\.(?:pdf|jpg|jpeg|png|gif|webp|svg|zip|rar|7z|mp4|mp3|avi|docx?|xlsx?|pptx?)$", re.I)
    def __init__(self, config: SocialFinderConfig, logger_=None):
        self.config=config; self.logger=logger_ or logger; self.stop_event=threading.Event(); self._local=threading.local()
    def stop(self): self.stop_event.set()
    def _session(self):
        session=getattr(self._local,"session",None)
        if session is None:
            session=requests.Session(); session.headers.update({"User-Agent":"YaBizTracker/1.1.2","Accept":"text/html,application/xhtml+xml;q=0.9,*/*;q=0.1","Accept-Language":"ru,en;q=0.7"}); self._local.session=session
        return session
    @staticmethod
    def _canonical(url):
        url=str(url or "").strip()
        if not url:return ""
        if not re.match(r"^https?://",url,re.I): url="https://"+url
        p=urlparse(url)
        return url if p.scheme.lower() in ("http","https") and p.netloc else ""
    @staticmethod
    def _domain(url): return (urlparse(url).hostname or "").lower().lstrip("www.")
    def _robots(self,start):
        if not self.config.respect_robots:return None
        rp=robotparser.RobotFileParser(); rp.set_url(urljoin(start,"/robots.txt"))
        try:
            r=self._session().get(rp.url,timeout=self.config.timeout_seconds); rp.parse(r.text.splitlines()); return rp
        except Exception as exc:
            self.logger.warning("Не удалось получить robots.txt для %s: %s",self._domain(start),exc); return None
    def _fetch(self,url,rp):
        if rp is not None and not rp.can_fetch("YaBizTracker",url): raise PermissionError(url)
        r=self._session().get(url,timeout=self.config.timeout_seconds,allow_redirects=True,stream=True); r.raise_for_status()
        ct=(r.headers.get("Content-Type") or "").lower()
        if ct and "html" not in ct and "xhtml" not in ct: r.close(); return "", ""
        chunks=[]; total=0
        for chunk in r.iter_content(65536):
            total+=len(chunk)
            if total>self.config.max_response_bytes: r.close(); raise ValueError("страница превышает допустимый размер")
            chunks.append(chunk)
        raw=b"".join(chunks); enc=r.encoding or r.apparent_encoding or "utf-8"; final=r.url; r.close(); return raw.decode(enc,errors="replace"),final
    def _candidates(self,current,parser,base):
        out=[]; seen=set()
        for href in parser.links:
            href=html.unescape(href).strip()
            if not href or href.lower().startswith(("javascript:","tel:","mailto:","#")): continue
            u=self._canonical(urljoin(current,href))
            if not u or self._domain(u)!=base or self.SKIP_EXTENSIONS.search(urlparse(u).path): continue
            if u not in seen:
                seen.add(u); score=10 if any(x in (href+" ").casefold() for x in self.CONTACT_HINTS) else 0; out.append((score,u))
        for path in self.CONTACT_PATHS:
            u=self._canonical(urljoin(current,path))
            if u and self._domain(u)==base and u not in seen: seen.add(u); out.append((8,u))
        out.sort(key=lambda x:(-x[0],len(x[1]))); return [u for _,u in out]
    def scan(self,org_id,website):
        start=self._canonical(website)
        if not start:return SocialScanResult(str(org_id),status="error",error="Некорректный URL сайта")
        rp=self._robots(start); base=self._domain(start); queue=[start]; visited=set(); links={}; pages=0
        try:
            while queue and pages<max(1,self.config.max_pages) and not self.stop_event.is_set():
                url=queue.pop(0)
                if url in visited: continue
                visited.add(url)
                try: text,final=self._fetch(url,rp)
                except PermissionError: continue
                except Exception as exc: self.logger.info("Пропуск страницы соцсетей %s: %s",url,type(exc).__name__); continue
                if not text: continue
                pages+=1; parser=_SocialPageParser()
                try: parser.feed(text)
                except Exception: pass
                found=extract_social_links(parser.links, parser.meta, text)
                for k,vals in found.items(): links.setdefault(k,[]); links[k].extend(x for x in vals if x not in links[k])
                queue.extend(self._candidates(final or url,parser,base))
            return SocialScanResult(str(org_id),links,"found" if links else "not_found","",pages)
        except Exception as exc: return SocialScanResult(str(org_id),links,"error",f"{type(exc).__name__}: {exc}",pages)
    def run(self,organizations,on_result):
        groups={}
        for org in organizations:
            oid=str(org.get("org_id") or org.get("id") or ""); website=self._canonical(org.get("website"))
            if oid and website: groups.setdefault(self._domain(website),{"website":website,"orgs":[]})["orgs"].append(org)
        q=Queue()
        for g in groups.values(): q.put(g)
        def worker():
            while not self.stop_event.is_set():
                try:g=q.get_nowait()
                except Empty:return
                try:
                    r=self.scan(str(g["orgs"][0].get("org_id") or g["orgs"][0].get("id")),g["website"])
                    for org in g["orgs"]:
                        on_result(SocialScanResult(str(org.get("org_id") or org.get("id")),dict(r.links),r.status,r.error,r.pages))
                finally:q.task_done()
        ts=[threading.Thread(target=worker,daemon=True,name="social-finder") for _ in range(max(1,min(32,self.config.workers)))]
        for t in ts:t.start()
        for t in ts:t.join()
