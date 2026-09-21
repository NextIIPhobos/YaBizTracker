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

    def log_general(self, level, msg):
        self.recent.append(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}")
        self.log_message.emit(datetime.now().strftime("%H:%M:%S"), level, msg)
        getattr(self.logger, {"OK":"info", "INFO":"info", "WARNING":"warning", "ERROR":"error"}.get(level, "info"))(msg)
