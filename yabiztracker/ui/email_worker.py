from __future__ import annotations
from PyQt6.QtCore import QThread, pyqtSignal

from ..services.email_finder import EmailFinderConfig, WebsiteEmailFinder


class EmailFinderWorker(QThread):
    progress = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(object)

    def __init__(self, db, settings, organizations=None, force=False):
        super().__init__()
        self.db = db
        cfg = settings.get("email_finder", {}) or {}
        self.config = EmailFinderConfig(
            enabled=bool(cfg.get("enabled", True)),
            workers=max(1, min(32, int(cfg.get("workers", 8)))),
            max_pages=max(1, min(20, int(cfg.get("max_pages", 5)))),
            timeout_seconds=max(3.0, min(60.0, float(cfg.get("timeout_seconds", 12)))),
            max_response_bytes=max(64 * 1024, min(10 * 1024 * 1024, int(cfg.get("max_response_bytes", 2 * 1024 * 1024)))),
            recheck_days=max(1, min(365, int(cfg.get("recheck_days", 30)))),
            respect_robots=bool(cfg.get("respect_robots", True)),
        )
        self.finder = WebsiteEmailFinder(db, self.config)
        self.organizations = list(organizations or [])
        self.force = bool(force)

    def stop(self):
        self.finder.stop()
        self.requestInterruption()

    def run(self):
        try:
            if not self.config.enabled:
                self.completed.emit({"queued": 0, "processed": 0, "found": 0, "not_found": 0, "errors": 0, "blocked": 0, "cancelled": False})
                return
            candidates = self.organizations or self.db.get_email_scan_candidates(self.config.recheck_days)
            if not candidates:
                self.completed.emit({"queued": 0, "processed": 0, "found": 0, "not_found": 0, "errors": 0, "blocked": 0, "cancelled": False})
                return
            normalized = []
            for raw in candidates:
                org = dict(raw)
                org_id = org.get("org_id") or org.get("id")
                if not org_id:
                    continue
                org["org_id"] = str(org_id)
                org["id"] = str(org_id)
                normalized.append(org)
            candidates = normalized
            self.db.mark_email_scan_queued([o["org_id"] for o in candidates])
            stats = {"queued": len(candidates), "processed": 0, "found": 0, "not_found": 0, "errors": 0, "blocked": 0, "cancelled": False}

            def on_result(result):
                if self.isInterruptionRequested():
                    self.finder.stop()
                self.db.update_organization_emails(result.org_id, result.emails, result.status, result.error, result.pages)
                stats["processed"] += 1
                stats[result.status if result.status in stats else "errors"] += 1
                self.progress.emit({**stats, "org_id": result.org_id, "emails": result.emails, "status": result.status, "error": result.error, "pages": result.pages})

            self.finder.run(candidates, on_result=on_result)
            stats["cancelled"] = self.isInterruptionRequested()
            self.completed.emit(stats)
        except Exception as exc:
            self.failed.emit(exc)
