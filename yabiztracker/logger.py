from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from PyQt6.QtCore import QObject, pyqtSignal


class AppLogger(QObject):
    log_message = pyqtSignal(str, str, str)

    def __init__(self, base_dir=None, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger("YaBizTracker")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.recent = deque(maxlen=100)
        if not self.logger.handlers:
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
            stream = logging.StreamHandler()
            stream.setFormatter(formatter)
            self.logger.addHandler(stream)
            if base_dir:
                log_dir = os.path.join(base_dir, "logs")
                os.makedirs(log_dir, exist_ok=True)
                file_handler = RotatingFileHandler(
                    os.path.join(log_dir, "app.log"), maxBytes=10 * 1024 * 1024,
                    backupCount=7, encoding="utf-8", delay=True
                )
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)

    def clear_logs(self, base_dir=None) -> int:
        """Close log handlers, remove log files, and reopen the active log."""
        removed = 0
        for handler in list(self.logger.handlers):
            if isinstance(handler, RotatingFileHandler):
                try:
                    handler.flush(); handler.close()
                finally:
                    self.logger.removeHandler(handler)
                try:
                    if os.path.exists(handler.baseFilename):
                        os.remove(handler.baseFilename); removed += 1
                except OSError:
                    pass
        root = os.path.abspath(base_dir) if base_dir else ""
        log_dir = os.path.join(root, "logs") if root else ""
        if log_dir and os.path.isdir(log_dir):
            for dirpath, _, filenames in os.walk(log_dir):
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    try:
                        os.remove(path); removed += 1
                    except OSError:
                        pass
        if base_dir:
            log_dir = os.path.join(os.path.abspath(base_dir), "logs")
            os.makedirs(log_dir, exist_ok=True)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
            file_handler = RotatingFileHandler(os.path.join(log_dir, "app.log"), maxBytes=10*1024*1024, backupCount=7, encoding="utf-8", delay=True)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        return removed

    def log_general(self, level, msg):
        self.recent.append(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}")
        self.log_message.emit(datetime.now().strftime("%H:%M:%S"), level, msg)
        getattr(self.logger, {"OK":"info", "INFO":"info", "WARNING":"warning", "ERROR":"error"}.get(level, "info"))(msg)
