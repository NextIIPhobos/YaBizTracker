from __future__ import annotations
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal

from ..domain.scan import scan_signature



class ScanWorker(QThread):
    progress=pyqtSignal(dict)
    completed=pyqtSignal(dict)
    failed=pyqtSignal(object)
    def __init__(self,api,db,cities,categories,excluded_categories=None):
        super().__init__();self.api=api;self.db=db;self.cities=cities;self.categories=categories;self.excluded_categories=excluded_categories or []
    def run(self):
        started=datetime.now();run_id=None
        try:
            signature=scan_signature(self.cities,self.categories,self.excluded_categories)
            run_id,resumed=self.db.start_or_resume_scan(signature,self.cities,self.categories)
            def cancelled(): return self.isInterruptionRequested()
            def get_start_skip(city,category): return self.db.get_checkpoint(run_id,city.get("name",""),category)[0]
            def on_page(city,category,skip,page_orgs,raw_features):
                new,updated,ignored,duplicates_db,new_items=self.db.upsert_organizations(
                    page_orgs, city.get("name", ""), search_category=category
                )
                st_acc=self._acc
                st_acc["new_count"]+=new; st_acc["updated"]+=updated; st_acc["ignored"]+=ignored; st_acc["duplicates_db"]+=duplicates_db; st_acc["new_items"].extend(new_items)
                # If Yandex explicitly reports a permanent closure, remove the lead
                # from the active table immediately, but keep a full archive snapshot.
                for org in page_orgs:
                    if org.get("source_status") == "closed" and self.db.archive_deleted(
                        org.get("id"), "yandex_explicit_closed"):
                        st_acc["deleted"] += 1
            def on_checkpoint(city,category,next_skip,pages_completed):
                self.db.save_checkpoint(run_id,city.get("name",""),category,next_skip,pages_completed)
            def on_category_complete(city, category, all_seen_ids, truncated, fresh_category_scan):
                # Reconcile only after a successful category scan. The DB method applies
                # a conservative multi-scan threshold and protects active CRM leads.
                result = self.db.reconcile_category(
                    city.get("name", ""), category, all_seen_ids,
                    scan_complete=fresh_category_scan, truncated=truncated, threshold=3
                )
                self._acc["deleted"] += result.get("deleted", 0)
                self._acc["stale_candidates"] += result.get("candidates", 0)
            self._acc={"new_count":0,"updated":0,"ignored":0,"duplicates_db":0,"new_items":[],"deleted":0,"stale_candidates":0}
            def progress(city,query,ci,total,skip,stats):
                self.progress.emit({"city":city,"category":query,"category_index":ci,"categories_total":total,"page":skip//50+1,"pages":stats["pages"],"api_results":stats["api_results"],"resumed":resumed})
            orgs,st=self.api.search_organizations(self.cities,self.categories,excluded_categories=self.excluded_categories,cancel=cancelled,progress=progress,on_page=on_page,get_start_skip=get_start_skip,on_checkpoint=on_checkpoint,on_category_complete=on_category_complete)
            st["without_phone"]=sum(not o.get("phone") for o in orgs)
            st["without_email"]=sum(not o.get("email") for o in orgs)
            st["without_website"]=sum(not o.get("website") for o in orgs)
            st["without_coordinates"]=sum(not (o.get("latitude") is not None and o.get("longitude") is not None) for o in orgs)
            st.update(self._acc)
            st["duplicates"]=st.get("duplicates",0)+self._acc["duplicates_db"]
            status="cancelled" if st.get("cancelled") or cancelled() else "completed"
            self.db.finish_scan_run(run_id,status)
            st.update({"started_at":started.isoformat(timespec="seconds"),"finished_at":datetime.now().isoformat(timespec="seconds"),"cancelled":status=="cancelled","resumed":resumed})
            self.completed.emit(st)
        except Exception as e:
            if run_id is not None:
                try:self.db.finish_scan_run(run_id,"failed",f"{type(e).__name__}: {e}")
                except Exception:pass
            self.failed.emit(e)
