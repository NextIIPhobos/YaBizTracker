from __future__ import annotations

import os
import sqlite3
from .services.backup import BackupError, restore_backup_to_path, verify_sqlite_file, backup_sqlite_file, BACKUP_RE
from .database.database import SCHEMA_VERSION


def _backups(base_dir, settings):
    raw = (settings.get("backup", {}) or {}).get("path", "backups")
    return os.path.abspath(raw if os.path.isabs(str(raw)) else os.path.join(base_dir, str(raw)))


def prepare_database(base_dir: str):
    db_path = os.path.join(base_dir, "organizations.db")
    from .services.settings import load_json, migrate_settings
    settings = migrate_settings(load_json(os.path.join(base_dir, "settings.json")))
    if not os.path.exists(db_path):
        return True, ""
    ok, detail = verify_sqlite_file(db_path)
    if ok:
        try:
            conn=sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro",uri=True,timeout=5)
            try: schema=int(conn.execute("PRAGMA user_version").fetchone()[0])
            finally: conn.close()
        except Exception as exc:
            return False, f"Не удалось определить версию схемы БД: {exc}"
        if schema > SCHEMA_VERSION:
            return False, f"База создана более новой версией программы (схема {schema}, поддерживается {SCHEMA_VERSION}). Обновите приложение."
        if schema < SCHEMA_VERSION and bool((settings.get("backup",{}) or {}).get("enabled",True)):
            try:
                backup_dir=_backups(base_dir,settings); os.makedirs(backup_dir,exist_ok=True)
                stamp=__import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d_%H-%M-%S")
                target=os.path.join(backup_dir,f"organizations_{stamp}_pre-migration.db")
                backup_sqlite_file(db_path,target)
                bok,bdetail=verify_sqlite_file(target)
                if not bok: raise BackupError(bdetail)
            except Exception as exc:
                return False, f"Перед миграцией не удалось создать резервную копию БД. Запуск остановлен для защиты данных.\n{exc}"
        return True, ""
    backup_dir = _backups(base_dir, settings)
    candidates = []
    if os.path.isdir(backup_dir):
        candidates = sorted([os.path.join(backup_dir, x) for x in os.listdir(backup_dir) if BACKUP_RE.match(x)], reverse=True)
    valid = None
    for path in candidates:
        bok, _ = verify_sqlite_file(path)
        if bok:
            valid = path
            break
    if not valid:
        return False, ("База данных повреждена и действительной резервной копии нет.\n\n"
                       f"Ошибка SQLite: {detail}\n\n"
                       "Не удаляйте organizations.db. Сохраните файл для восстановления вручную.")
    from PyQt6.QtWidgets import QMessageBox
    answer = QMessageBox.question(
        None, "База данных повреждена",
        "База данных повреждена.\n\n"
        f"Последняя рабочая резервная копия:\n{valid}\n\n"
        "Восстановить её сейчас? Текущий повреждённый файл будет сохранён как .corrupt_...",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False, "База данных повреждена. Запуск отменён, чтобы не потерять данные."
    try:
        restore_backup_to_path(valid, db_path)
        return True, ""
    except Exception as exc:
        return False, f"Не удалось восстановить базу из резервной копии:\n{exc}"
