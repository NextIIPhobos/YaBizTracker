from __future__ import annotations

import json

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMenu

from ..services.social_finder import SOCIAL_LABELS, extract_social_links, merge_social_links


def parse_social_links(raw) -> dict[str, list[str]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return extract_social_links(raw)
    return merge_social_links(raw)


def build_social_menu(parent, raw) -> QMenu | None:
    links = parse_social_links(raw)
    if not links:
        return None
    menu = QMenu(parent)
    for platform, urls in links.items():
        label = SOCIAL_LABELS.get(platform, platform)
        submenu = menu.addMenu(label)
        for url in urls:
            action = submenu.addAction(url)
            action.triggered.connect(lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl.fromUserInput(u)))
    return menu
