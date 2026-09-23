from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
BACKUP_RE = re.compile(r"^organizations_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_\d+|_pre-migration)?\.db$")


class BackupError(RuntimeError):
    pass


class BackupService:
    """Safe SQLite backup/restore using SQLite's online backup API."""

    def __init__(self, db, backup_dir: str, retention: int = 14):
        self.db = db
        self.backup_dir = os.path.abspath(os.path.expanduser(backup_dir))
        self.retention = max(1, int(retention))

    def list_backups(self) -> list[str]:
        if not os.path.isdir(self.backup_dir):
            return []
        items = []
        for name in os.listdir(self.backup_dir):
            if BACKUP_RE.match(name):
                items.append(os.path.join(self.backup_dir, name))
        return sorted(items, reverse=True)

    @staticmethod
    def _verify_file(path: str) -> tuple[bool, str]:
        conn = None
        try:
            conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True, timeout=5)
            row = conn.execute("PRAGMA quick_check").fetchone()
            result = str(row[0]) if row else ""
            return result.lower() == "ok", result
        except sqlite3.DatabaseError as exc:
            return False, str(exc)
        finally:
            if conn is not None:
                conn.close()

    def latest_valid_backup(self) -> str | None:
        for path in self.list_backups():
            ok, _ = self._verify_file(path)
            if ok:
                return path
        return None

    def create_backup(self, label: str | None = None) -> str:
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = label or datetime.now(MSK).strftime("%Y-%m-%d_%H-%M-%S")
        target = os.path.join(self.backup_dir, f"organizations_{stamp}.db")
        # Avoid overwriting an existing backup made in the same second.
        if os.path.exists(target):
            suffix = 1
            while os.path.exists(os.path.join(self.backup_dir, f"organizations_{stamp}_{suffix}.db")):
                suffix += 1
            target = os.path.join(self.backup_dir, f"organizations_{stamp}_{suffix}.db")

        tmp = target + ".tmp"
        try:
            self.db.backup_to(tmp)
            ok, detail = self._verify_file(tmp)
            if not ok:
                raise BackupError(f"Резервная копия не прошла проверку целостности: {detail}")
            os.replace(tmp, target)
            self.prune()
            return target
        except Exception as exc:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"Не удалось создать резервную копию: {exc}") from exc

    def prune(self) -> None:
        backups = self.list_backups()
        for path in backups[self.retention:]:
            try:
                os.remove(path)
            except OSError:
                pass

    def delete_all_backups(self) -> int:
        """Delete every managed backup in the configured backup directory."""
        removed = 0
        for path in self.list_backups():
            try:
                os.remove(path)
                removed += 1
            except OSError as exc:
                raise BackupError(f"Не удалось удалить резервную копию: {path}: {exc}") from exc
        return removed

    @staticmethod
    def delete_auxiliary_files(base_dir: str) -> int:
        """Remove safe-to-regenerate application leftovers, never user data."""
        import shutil
        base = os.path.abspath(base_dir)
        removed = 0
        patterns = (".tmp", ".restore.tmp")
        for root, dirs, files in os.walk(base):
            # Never touch backups, the database, or user configuration/data.
            dirs[:] = [d for d in dirs if d not in {"backups", ".git"}]
            for name in files:
                path = os.path.join(root, name)
                if name.endswith(patterns) or ".corrupt_" in name:
                    try:
                        os.remove(path); removed += 1
                    except OSError:
                        pass
            for d in list(dirs):
                if d == "__pycache__":
                    path = os.path.join(root, d)
                    try:
                        shutil.rmtree(path); removed += 1
                    except OSError:
                        pass
        return removed

    def restore(self, backup_path: str) -> None:
        backup_path = os.path.abspath(backup_path)
        if backup_path not in [os.path.abspath(x) for x in self.list_backups()]:
            raise BackupError("Указанная резервная копия не найдена в папке резервных копий.")
        ok, detail = self._verify_file(backup_path)
        if not ok:
            raise BackupError(f"Резервная копия повреждена: {detail}")
        self.db.restore_from(backup_path)


def verify_sqlite_file(path: str) -> tuple[bool, str]:
    """Read-only integrity check for a SQLite file that is not yet opened by Database."""
    return BackupService._verify_file(path)


def restore_backup_to_path(backup_path: str, db_path: str) -> None:
    """Restore a verified SQLite backup safely, including when the target DB is open.

    Windows does not allow renaming an SQLite WAL sidecar while another connection
    has it open. Therefore the current database is preserved through SQLite's
    backup API into a ``.corrupt_*`` snapshot, and the verified backup is then
    restored through the API instead of renaming the live database file.
    """
    ok, detail = verify_sqlite_file(backup_path)
    if not ok:
        raise BackupError(f"Резервная копия повреждена: {detail}")

    db_path = os.path.abspath(db_path)
    backup_path = os.path.abspath(backup_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    stamp = datetime.now(MSK).strftime("%Y%m%d_%H%M%S")
    corrupt = f"{db_path}.corrupt_{stamp}"
    corrupt_tmp = corrupt + ".tmp"

    source = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True, timeout=5)
    current = None
    restore = None
    try:
        # Preserve the currently installed database before overwriting it. This
        # works even if the application still has another connection open.
        if os.path.exists(db_path):
            current = sqlite3.connect(db_path, timeout=5)
            if os.path.exists(corrupt_tmp):
                os.remove(corrupt_tmp)
            preserved = sqlite3.connect(corrupt_tmp)
            try:
                current.backup(preserved, pages=100, sleep=0.05)
                preserved.commit()
            finally:
                preserved.close()
            current.close()
            current = None
            ok, detail = verify_sqlite_file(corrupt_tmp)
            if not ok:
                raise BackupError(f"Не удалось сохранить текущую БД перед восстановлением: {detail}")
            os.replace(corrupt_tmp, corrupt)

        # Restore through SQLite itself. This avoids renaming a live DB/WAL file
        # and is safe when another application connection is present.
        restore = sqlite3.connect(db_path, timeout=10)
        try:
            restore.execute("PRAGMA busy_timeout=10000")
            source.backup(restore, pages=100, sleep=0.05)
            restore.commit()
            restore.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            restore.commit()
        finally:
            restore.close()
            restore = None

        ok, detail = verify_sqlite_file(db_path)
        if not ok:
            raise BackupError(f"Восстановленная БД не прошла проверку целостности: {detail}")
    except BackupError:
        raise
    except Exception as exc:
        if os.path.exists(corrupt_tmp):
            try:
                os.remove(corrupt_tmp)
            except OSError:
                pass
        raise BackupError(f"Не удалось восстановить резервную копию: {exc}") from exc
    finally:
        if current is not None:
            current.close()
        if restore is not None:
            restore.close()
        source.close()


def backup_sqlite_file(source_path: str, target_path: str) -> None:
    """Backup a SQLite file before application-level migrations."""
    source = sqlite3.connect(f"file:{os.path.abspath(source_path)}?mode=ro", uri=True, timeout=5)
    try:
        if os.path.exists(target_path):
            os.remove(target_path)
        dest = sqlite3.connect(target_path)
        try:
            source.backup(dest, pages=100, sleep=0.05)
            dest.commit()
        finally:
            dest.close()
    finally:
        source.close()
