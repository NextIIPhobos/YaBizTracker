import pytest
pytest.importorskip("PyQt6")

from yabiztracker.ui.social_menu import parse_social_links


def test_social_menu_accepts_displayed_semicolon_separated_urls():
    links = parse_social_links("https://vk.com/example; https://max.ru/channel; https://t.me/channel")
    assert links["vk"] == ["https://vk.com/example"]
    assert links["max"] == ["https://max.ru/channel"]
    assert links["telegram"] == ["https://t.me/channel"]
