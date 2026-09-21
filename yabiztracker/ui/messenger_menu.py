from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMenu

from ..domain.phone import messenger_url

MESSENGERS = ("Telegram", "WhatsApp", "Viber", "Max")


def has_messenger_links(phone: str) -> bool:
    return any(messenger_url(name, phone) for name in MESSENGERS)


def build_messenger_menu(parent, phones: list[str]) -> QMenu | None:
    valid = [phone for phone in phones if has_messenger_links(phone)]
    if not valid:
        return None
    menu = QMenu(parent)
    for messenger in MESSENGERS:
        submenu = menu.addMenu(messenger)
        for phone in valid:
            url = messenger_url(messenger, phone)
            if not url:
                continue
            action = submenu.addAction(phone)
            action.triggered.connect(lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
    return menu
