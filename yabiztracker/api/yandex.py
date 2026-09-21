from __future__ import annotations
import json, logging, random, time, re, threading
import requests
from .errors import ApiError, ApiLimitError, ApiAuthError, ApiNetworkError, ApiServerError, ApiInvalidResponseError
from .. import __version__
from ..domain.filters import excluded_category_match
logger=logging.getLogger(__name__)

class YandexSearchClient:
    URL="https://search-maps.yandex.ru/v1/"
    def __init__(self, key, usage=None):
        self.key = key
        self.usage = usage
        self._sessions = threading.local()

    def _session(self):
        session = getattr(self._sessions, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": f"YaBizTracker/{__version__}"})
            self._sessions.session = session
        return session

    def _request(self, params, timeout=12):
        return _request(self._session(), self.URL, params, timeout, "search", self.usage)

    def search_page(self,text,bbox,skip=0):
        r=self._request({"apikey":self.key,"text":text,"bbox":bbox,"rspn":1,"type":"biz","lang":"ru_RU","results":50,"skip":skip})
        try: data=r.json()
        except ValueError as e: raise ApiInvalidResponseError("API вернул некорректный JSON",api="search",technical=str(e))
        fs=data.get("features")
        if not isinstance(fs,list): raise ApiInvalidResponseError("API вернул неожиданный формат Search API",api="search")
        return fs, len(fs)==50

    def resolve_uri(self,uri):
        r=self._request({"apikey":self.key,"uri":uri,"type":"geo","lang":"ru_RU","results":1},12)
        try:return r.json().get("features",[]) or []
        except ValueError as e:raise ApiInvalidResponseError("Некорректный JSON Search API",api="search",technical=str(e))

class YandexGeocoderClient:
    URL="https://geocode-maps.yandex.ru/v1/"
    def __init__(self, key, usage=None):
        self.key = key
        self.usage = usage
        self._sessions = threading.local()

    def _session(self):
        session = getattr(self._sessions, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": f"YaBizTracker/{__version__}"})
            self._sessions.session = session
        return session

    def _request(self, params, timeout=12):
        return _request(self._session(), self.URL, params, timeout, "geocoder", self.usage)

    def geocode(self,text,results=10,timeout=12):
        r=self._request({"apikey":self.key,"geocode":text,"format":"json","lang":"ru_RU","results":results},timeout)
        try:return r.json()
        except ValueError as e:raise ApiInvalidResponseError("Некорректный JSON Геокодера",api="geocoder",technical=str(e))

class YandexAPI:
    def __init__(self,search_api_key,geocoder_key="",usage=None):
        self.search=YandexSearchClient(search_api_key,usage)
        self.geocoder=YandexGeocoderClient(geocoder_key,usage)
        self.last_quota={"search":None,"geocoder":None,"js":None}
        self.usage=usage

    def test_search_key(self, bbox="50.0,53.0~50.3,53.4"):
        try:
            self.search.search_page("кафе",bbox,0); return True,"Ключ работает"
        except ApiError as e:return False,str(e)
    def test_geocoder_key(self):
        try:
            self.geocoder.geocode("Россия",1); return True,"Ключ работает"
        except ApiError as e:return False,str(e)

    @staticmethod
    def _parse_city(g,name=""):
        meta=(g.get("metaDataProperty",{}) or {}).get("GeocoderMetaData",{}) or {}
        if meta.get("kind")!="locality": return None
        pos=(g.get("Point",{}) or {}).get("pos","").split()
        env=(g.get("boundedBy",{}) or {}).get("Envelope",{}) or {}
        lo=(env.get("lowerCorner","") or "").split(); hi=(env.get("upperCorner","") or "").split()
        if len(pos)<2 or len(lo)<2 or len(hi)<2:return None
        lon,lat=map(float,pos[:2]); x1,y1=map(float,lo[:2]); x2,y2=map(float,hi[:2])
        return {"name":g.get("name") or name,"description":g.get("description") or meta.get("text") or "",
                "uri":meta.get("uri") or "","latitude":lat,"longitude":lon,"bbox":f"{x1},{y1}~{x2},{y2}"}

    def suggest_settlements(self,text):
        d=self.geocoder.geocode(text.strip(),10,timeout=5)
        members=d.get("response",{}).get("GeoObjectCollection",{}).get("featureMember",[]) or []
        out=[]; seen=set()
        for m in members:
            c=self._parse_city(m.get("GeoObject",{}),text)
            if c and c["name"].lower() not in seen:
                seen.add(c["name"].lower()); out.append(c)
        return out

    def resolve_settlement(self,value):
        if isinstance(value,dict) and value.get("latitude") is not None and value.get("bbox"):return value
        value=str(value or "").strip()
        if not value:return None
        if value.startswith("ymapsbm"):
            fs=self.search.resolve_uri(value)
            if fs:
                f=fs[0]; p=f.get("properties",{}) or {}; meta=p.get("GeocoderMetaData",{}) or {}
                coords=(f.get("geometry",{}) or {}).get("coordinates",[])
                b=p.get("boundedBy")
                if meta.get("kind")=="locality" and len(coords)>=2:
                    if b and len(b)==2:
                        (x1,y1),(x2,y2)=b; bbox=f"{x1},{y1}~{x2},{y2}"
                        return {"name":p.get("name") or value,"description":p.get("description") or meta.get("text") or "",
                                "uri":value,"latitude":float(coords[1]),"longitude":float(coords[0]),"bbox":bbox}
        d=self.geocoder.geocode(value,10)
        for m in d.get("response",{}).get("GeoObjectCollection",{}).get("featureMember",[]) or []:
            c=self._parse_city(m.get("GeoObject",{}),value)
            if c:return c
        return None

    @staticmethod
    def parse_org(feature):
        p=feature.get("properties",{}) or {}; meta=p.get("CompanyMetaData",{}) or {}
        coords=(feature.get("geometry",{}) or {}).get("coordinates",[])
        if len(coords)<2:return None
        oid=str(meta.get("id") or p.get("id") or "").strip()
        uri=p.get("uri","")
        if not oid and "oid=" in uri:oid=uri.split("oid=",1)[1].split("&",1)[0]
        name=str(p.get("name") or meta.get("name") or "").strip()
        if not oid or not name:return None
        def first(*vals):
            for v in vals:
                if isinstance(v,str) and v.strip():return v.strip()
            return ""
        addr=meta.get("Address",{}) or {}
        phones=[]
        for x in meta.get("Phones",[]) or []:
            if isinstance(x,dict):x=first(x.get("formatted"),x.get("number"))
            if x:phones.append(str(x))
        cats=[]
        for x in meta.get("Categories",[]) or []:
            x=x.get("name") if isinstance(x,dict) else x
            if x:cats.append(str(x))
        # Yandex may expose organization state in different metadata versions.
        # Keep this parser deliberately tolerant; unknown means we must not delete.
        raw_status = " ".join(str(meta.get(k) or p.get(k) or "") for k in ("status", "Status", "state", "State", "businessStatus"))
        raw_status_low = raw_status.lower()
        if any(x in raw_status_low for x in ("закрыт", "больше не работает", "shutdown", "closed", "defunct")):
            source_status = "closed"
        elif any(x in raw_status_low for x in ("временно не работает", "временно закрыт", "temporarily closed")):
            source_status = "temporarily_closed"
        elif raw_status:
            source_status = "open"
        else:
            source_status = "unknown"
        socials={}
        for x in meta.get("Links") or meta.get("links") or []:
            if not isinstance(x,dict):continue
            u=first(x.get("href"),x.get("url")); low=u.lower()
            if "vk.com" in low:socials["vk"]=u
            elif "t.me" in low or "telegram" in low:socials["telegram"]=u
            elif "instagram.com" in low:socials["instagram"]=u
            elif u:socials.setdefault("other",u)
        return {"id":oid,"name":name,"address":first(addr.get("formatted"),p.get("description")),
                "category":cats[0] if cats else "","subcategory":cats[1] if len(cats)>1 else "",
                "categories":cats,
                "phone":", ".join(dict.fromkeys(phones)),
                "website":first(meta.get("url"),p.get("url")),"email":first(meta.get("email"),p.get("email")),
                "social_links":json.dumps(socials,ensure_ascii=False),"source_status":source_status,
                "latitude":float(coords[1]),"longitude":float(coords[0])}

    def search_organizations(self,cities,categories,excluded_categories=None,cancel=None,progress=None,on_page=None,get_start_skip=None,on_checkpoint=None,on_category_complete=None):
        """Scan page-by-page. Callbacks allow durable checkpointing after every page."""
        unique={}; stats={"pages":0,"api_results":0,"failed_pages":[],"categories_failed":[],"search_requests":0,"excluded_by_category":0,"accepted_results":0}
        excluded=list(excluded_categories or [])
        for city in cities:
            for ci,query in enumerate(categories,1):
                skip = int(get_start_skip(city, query) if get_start_skip else 0)
                fresh_category_scan = skip == 0
                if skip < 0:
                    continue
                category_failed=False
                category_seen=set()
                page_number = skip // 50 + 1
                while True:
                    if cancel and cancel():
                        stats["cancelled"]=True; stats["unique_found"]=len(unique); stats["duplicates"]=max(0,stats["accepted_results"]-len(unique)); return list(unique.values()),stats
                    try:
                        stats["search_requests"] += 1
                        fs,more=self.search.search_page(query,city["bbox"],skip)
                    except ApiLimitError: raise
                    except (ApiServerError,ApiNetworkError) as e:
                        stats["failed_pages"].append(f"{city['name']} / {query} / skip={skip}: {e}")
                        category_failed=True; break
                    stats["pages"]+=1; stats["api_results"]+=len(fs)
                    page_orgs=[]
                    for f in fs:
                        o=self.parse_org(f)
                        if o:
                            if excluded_category_match(o, excluded):
                                stats["excluded_by_category"] += 1
                                continue
                            stats["accepted_results"] += 1
                            o["city_name"]=city["name"]; unique[o["id"]]=o; category_seen.add(o["id"]); page_orgs.append(o)
                    if on_page:
                        on_page(city, query, skip, page_orgs, fs)
                    next_skip = skip + 50 if more and skip < 1000 else -1
                    if on_checkpoint:
                        on_checkpoint(city, query, next_skip, page_number)
                    if progress: progress(city["name"],query,ci,len(categories),skip,stats)
                    if not more or skip>=1000:break
                    skip+=50; page_number+=1
                if category_failed:
                    stats["categories_failed"].append(f"{city['name']} / {query}")
                elif on_category_complete:
                    # skip reaches 1000 only when the API result set is truncated by its hard limit.
                    on_category_complete(city, query, list(category_seen), skip >= 1000, fresh_category_scan)
        stats["unique_found"]=len(unique); stats["duplicates"]=max(0,stats["accepted_results"]-len(unique))
        return list(unique.values()),stats

def _error_text(r):
    try:
        d=r.json(); return str(d.get("message") or d.get("error") or r.text[:500])
    except Exception:return r.text[:500]

def _quota(text):
    m=re.search(r"Limit\s*:\s*(\d+).*?current value\s*:\s*(\d+)",text,re.I|re.S)
    if not m:m=re.search(r"лимит\D*(\d+).*?(?:текущее значение|current value)\D*(\d+)",text,re.I|re.S)
    return (int(m.group(2)),int(m.group(1))) if m else None

def _request(session,url,params,timeout,api,usage,retries=5):
    for attempt in range(retries):
        if usage: usage.record(api)
        try:
            r=session.get(url,params=params,timeout=timeout)
        except requests.RequestException as e:
            if attempt==retries-1: raise ApiNetworkError("Нет подключения к API",api=api,technical=str(e))
            time.sleep(min(8,2**attempt)+random.uniform(0,.25)); continue
        text=_error_text(r)
        _quota(text)
        if r.status_code==200:return r
        if r.status_code in (401,):
            raise ApiAuthError(f"Ключ {api} API недействителен или не имеет доступа",api=api,status=r.status_code,technical=text)
        if r.status_code==403:
            if "limit" in text.lower() or "quota" in text.lower() or "лимит" in text.lower():
                raise ApiLimitError("Лимит запросов API исчерпан. Проверьте Кабинет API Яндекс Карты.",api=api,status=403,technical=text)
            raise ApiAuthError(f"Доступ к {api} API запрещён. Проверьте ключ и ограничения.",api=api,status=403,technical=text)
        if r.status_code==429:
            if attempt==retries-1: raise ApiLimitError("Лимит запросов API исчерпан. Проверьте Кабинет API Яндекс Карты.",api=api,status=429,technical=text)
            retry_after=r.headers.get("Retry-After")
            try: delay=float(retry_after)
            except (TypeError,ValueError): delay=min(8,2**attempt)
            time.sleep(min(30,max(0,delay)) + random.uniform(0,.25)); continue
        if r.status_code in (500,502,503,504):
            if attempt==retries-1: raise ApiServerError(f"HTTP {r.status_code}: сервер API временно недоступен",api=api,status=r.status_code,technical=text)
            time.sleep(min(8,2**attempt)+random.uniform(0,.25)); continue
        raise ApiError(f"HTTP {r.status_code}: {text}",api=api,status=r.status_code,technical=text)
    raise ApiError("API не вернул ответ",api=api)
