from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from ..services.export_service import ExportService
from .social_worker import SocialFinderWorker
from ..domain.table import OrgColumn


class SocialScanController:
    def __init__(self, window):
        self.window = window
        self.worker = None

    def start(self, organizations=None, force=False):
        if self.worker and self.worker.isRunning():
            self.window.logger.log_general("INFO", "Поиск соц. сетей уже выполняется; новый запуск не создан.")
            return False
        cfg = self.window.settings.get("social_finder", {}) or {}
        if not bool(cfg.get("enabled", True)) and not force:
            self.window.logger.log_general("INFO", "Автоматический поиск соц. сетей отключён в настройках.")
            return False
        self.worker = SocialFinderWorker(self.window.db, self.window.settings, organizations=organizations, force=force)
        self.worker.progress.connect(self.progress)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.start()
        self.window.logger.log_general("INFO", ("Ручной" if force else "Фоновый") + " поиск соц. сетей запущен.")
        return True

    def manual(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self.window, "Поиск соц. сетей", "Поиск соц. сетей уже выполняется.")
            return
        organizations = self.window.db.get_all_organizations()
        if not organizations:
            QMessageBox.information(self.window, "Поиск соц. сетей", "В базе пока нет найденных организаций.")
            return
        self.start(organizations=organizations, force=True)
        self.window.progress_label.setText(f"Ручной поиск соц. сетей: 0/{len(organizations)} организаций")

    def progress(self, data):
        queued = int(data.get("queued", 0)); processed = int(data.get("processed", 0))
        if queued:
            self.window.progress_label.setText(f"Поиск соц. сетей: {processed}/{queued} организаций | найдено: {int(data.get('found', 0))}")
        oid = str(data.get("org_id") or "")
        if oid:
            self.refresh_row(oid)

    def refresh_row(self, oid):
        for row in range(self.window.org_table.rowCount()):
            item = self.window.org_table.item(row, OrgColumn.NAME)
            if not item or str(item.data(Qt.ItemDataRole.UserRole)) != oid:
                continue
            org = self.window.db.get_by_id(oid)
            if org:
                cell = self.window.org_table.item(row, OrgColumn.SOCIAL)
                if cell:
                    self.window._updating_table = True
                    try:
                        cell.setText(ExportService.social_text(org.get("social_links", "{}")))
                    finally:
                        self.window._updating_table = False
            return

    def completed(self, stats):
        self.window.refresh_all()
        self.window.logger.log_general("INFO", f"Поиск соц. сетей завершён: организаций={stats.get('queued', 0)}, обработано={stats.get('processed', 0)}, найдено={stats.get('found', 0)}, без ссылок={stats.get('not_found', 0)}, ошибок={stats.get('errors', 0)}")

    def failed(self, error):
        self.window.logger.log_general("ERROR", f"Поиск соц. сетей завершился ошибкой: {type(error).__name__}: {error}")
