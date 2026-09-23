from __future__ import annotations
from PyQt6.QtCore import QThread, pyqtSignal
from ..services.social_finder import SocialFinderConfig, WebsiteSocialFinder
from ..domain.socials import extract_social_links

class SocialFinderWorker(QThread):
    progress=pyqtSignal(dict); completed=pyqtSignal(dict); failed=pyqtSignal(object)
    def __init__(self,db,settings,organizations=None,api=None):
        super().__init__(); cfg=settings.get("email_finder",{}) or {}; self.config=SocialFinderConfig(workers=max(1,min(32,int(cfg.get("workers",8)))),max_pages=max(1,min(20,int(cfg.get("max_pages",5)))),timeout_seconds=max(3.0,min(60.0,float(cfg.get("timeout_seconds",12)))),max_response_bytes=max(64*1024,min(10*1024*1024,int(cfg.get("max_response_bytes",2*1024*1024)))),respect_robots=bool(cfg.get("respect_robots",True))); self.finder=WebsiteSocialFinder(self.config); self.db=db; self.api=api; self.organizations=list(organizations or [])
    def stop(self): self.finder.stop(); self.requestInterruption()
    def run(self):
        try:
            candidates=[dict(x) for x in (self.organizations or self.db.get_all_organizations())]
            stats={"queued":len(candidates),"processed":0,"found":0,"updated":0,"not_found":0,"errors":0,"api_found":0,"site_found":0,"cancelled":False}
            def process(org, site_links):
                oid=str(org.get("org_id") or org.get("id") or ""); merged=extract_social_links(site_links); changed=self.db.update_organization_social_links(oid,merged); stats["processed"]+=1; stats["updated"]+=int(changed); stats["found"]+=int(bool(merged)); self.progress.emit({**stats,"org_id":oid,"links":merged,"status":"found" if merged else "not_found"})
            for org in candidates:
                if self.isInterruptionRequested(): self.finder.stop(); break
                oid=str(org.get("org_id") or org.get("id") or "")
                links={}
                if self.api and oid:
                    try:
                        features=self.api.search.resolve_organization(oid)
                        for feature in features:
                            links=extract_social_links(feature)
                        if links: stats["api_found"]+=1
                    except Exception:
                        stats["errors"]+=1
                # Website scan is the fallback/enrichment source. It is also run when Yandex supplied links,
                # because businesses often publish additional social profiles on their own site.
                website=str(org.get("website") or "").strip()
                if website:
                    result=self.finder.scan(oid,website)
                    if result.links:
                        stats["site_found"]+=1
                        for k,vals in result.links.items(): links.setdefault(k,[]); links[k].extend(v for v in vals if v not in links[k])
                process(org,links)
            stats["cancelled"]=self.isInterruptionRequested(); self.completed.emit(stats)
        except Exception as exc:self.failed.emit(exc)
