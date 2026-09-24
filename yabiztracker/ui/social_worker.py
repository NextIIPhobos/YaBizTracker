from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from ..services.social_finder import SocialFinderConfig, SocialLinkFinder


class SocialFinderWorker(QThread):
    progress = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(object)

    def __init__(self, db, settings, organizations=None, force=False):
        super().__init__()
        cfg = settings.get("social_finder", {}) or {}
        self.config = SocialFinderConfig(
            enabled=bool(cfg.get("enabled", True)),
            workers=max(1, min(32, int(cfg.get("workers", 8)))),
            timeout_seconds=max(3.0, min(60.0, float(cfg.get("timeout_seconds", 10)))),
            max_response_bytes=max(64 * 1024, min(10 * 1024 * 1024, int(cfg.get("max_response_bytes", 3 * 1024 * 1024)))),
            website_pages=max(1, min(5, int(cfg.get("website_pages", 3)))),
            validate_links=bool(cfg.get("validate_links", True)),
        )
        self.db = db
        self.finder = SocialLinkFinder(db, self.config)
        self.organizations = list(organizations or [])
        self.force = bool(force)

    def stop(self):
        self.finder.stop()
        self.requestInterruption()

    def run(self):
        try:
            if not self.config.enabled and not self.force:
                self.completed.emit({"queued": 0, "processed": 0, "found": 0, "not_found": 0, "errors": 0, "cancelled": False})
                return
            candidates = self.organizations or self.db.get_social_scan_candidates(force=self.force)
            normalized = []
            for raw in candidates:
                org = dict(raw)
                org_id = org.get("org_id") or org.get("id")
                if org_id:
                    org["org_id"] = str(org_id)
                    org["id"] = str(org_id)
                    normalized.append(org)
            stats = {"queued": len(normalized), "processed": 0, "found": 0, "not_found": 0, "errors": 0, "cancelled": False}
            if not normalized:
                self.completed.emit(stats)
                return
            self.db.mark_social_scan_queued([o["org_id"] for o in normalized])

            def on_result(result):
                self.db.update_organization_socials(result.org_id, result.links, result.status, result.error)
                stats["processed"] += 1
                if result.status == "found":
                    stats["found"] += 1
                elif result.status == "not_found":
                    stats["not_found"] += 1
                else:
                    stats["errors"] += 1
                self.progress.emit({**stats, "org_id": result.org_id, "links": result.links, "status": result.status, "error": result.error})

            self.finder.run(normalized, on_result)
            stats["cancelled"] = self.isInterruptionRequested()
            self.completed.emit(stats)
        except Exception as exc:
            self.failed.emit(exc)
