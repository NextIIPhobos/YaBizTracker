from __future__ import annotations

import webbrowser
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMenu

from ..domain.phone import messenger_url

MESSENGERS = ("Telegram", "WhatsApp", "Viber", "Max")


def has_messenger_links(phone: str) -> bool:
    return any(messenger_url(name, phone) for name in MESSENGERS)


def _open_url(url: str) -> bool:
    """Open an external messenger URL through the OS default browser.

    QUrl.fromUserInput is used instead of the QUrl(string) constructor because
    messenger URLs contain a leading '+' in Telegram/WhatsApp/Max paths.
    The browser fallback also makes opening links reliable on portable
    Windows installations where the Qt desktop-services integration can fail.
    """
    if not url:
        return False
    qurl = QUrl.fromUserInput(url)
    opened = bool(qurl.isValid()) and QDesktopServices.openUrl(qurl)
    if not opened:
        try:
            opened = bool(webbrowser.open(url, new=2))
        except Exception:
            opened = False
    return opened


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
            action.triggered.connect(lambda _checked=False, u=url: _open_url(u))
    return menu
