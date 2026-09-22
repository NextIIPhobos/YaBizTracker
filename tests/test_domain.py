import unittest

from yabiztracker.domain.filters import excluded_category_match, matches_organization_filters, organization_categories
from yabiztracker.domain.selection import visible_range


class DomainLogicTests(unittest.TestCase):
    def test_category_match_uses_all_categories_case_insensitively(self):
        org = {"category": "Квесты", "subcategory": "Развлечения", "categories_json": '["Квесты", "Банк"]'}
        self.assertEqual(organization_categories(org), {"квесты", "банк"})
        self.assertTrue(excluded_category_match(org, ["банк"]))
        self.assertTrue(excluded_category_match(org, ["БАНК"]))
        self.assertFalse(excluded_category_match(org, ["Спорт"]))

    def test_category_fallback_survives_broken_json(self):
        org = {"category": "Квесты", "subcategory": "Развлечения", "categories_json": "not-json"}
        self.assertEqual(organization_categories(org), {"квесты", "развлечения"})

    def test_filter_predicate_matches_main_list_rules(self):
        org = {
            "name": "Банкрот Квест",
            "address": "Самара",
            "category": "Квесты",
            "subcategory": "Развлечения",
            "status": "Клиент",
            "phone": "+7",
            "email": "a@example.com",
            "website": "https://example.com",
            "social_links": '{"vk":"https://vk.com/a"}',
            "responsible": "Иван",
            "next_contact_date": "2026-09-20 12:00",
        }
        self.assertTrue(matches_organization_filters(org, {
            "search": "банкрот", "category": "Развлечения", "status": "Клиент",
            "phone_mode": "has", "email_mode": "has", "website_mode": "has", "social_mode": "has",
            "responsible_mode": "has", "next_contact_mode": "has",
        }))

    def test_social_empty_json_is_treated_as_missing(self):
        self.assertFalse(matches_organization_filters({"social_links": "{}"}, {"social_mode": "has"}))
        self.assertTrue(matches_organization_filters({"social_links": "{}"}, {"social_mode": "missing"}))
        self.assertTrue(matches_organization_filters({"social_links": '{"vk":"https://vk.com/a"}'}, {"social_mode": "has"}))

    def test_presence_modes_filter_has_and_missing_values(self):
        with_values = {"phone": "+7999", "email": "a@example.com", "website": "https://example.com", "social_links": "vk", "responsible": "Иван", "next_contact_date": "2026-09-20 12:00"}
        without_values = {"phone": "", "email": "", "website": "", "social_links": "", "responsible": "", "next_contact_date": ""}
        for mode_key, field in (("phone_mode", "phone"), ("email_mode", "email"), ("website_mode", "website"), ("social_mode", "social_links"), ("responsible_mode", "responsible"), ("next_contact_mode", "next_contact_date")):
            self.assertTrue(matches_organization_filters(with_values, {mode_key: "has"}))
            self.assertFalse(matches_organization_filters(without_values, {mode_key: "has"}))
            self.assertFalse(matches_organization_filters(with_values, {mode_key: "missing"}))
            self.assertTrue(matches_organization_filters(without_values, {mode_key: "missing"}))

    def test_shift_range_is_based_on_visible_order(self):
        visible = [0, 2, 5, 8]
        self.assertEqual(visible_range(visible, 0, 8), [0, 2, 5, 8])
        self.assertEqual(visible_range(visible, 5, 2), [2, 5])
        self.assertEqual(visible_range(visible, 1, 8), [8])
        self.assertEqual(visible_range([], 0, 1), [])

    def test_text_filter_includes_category_and_subcategory(self):
        org={"name":"ООО Ромашка","address":"Самара","category":"Детские сады","subcategory":"Детская одежда"}
        self.assertTrue(matches_organization_filters(org,{"search":"детская"}))
        self.assertTrue(matches_organization_filters(org,{"search":"сады"}))
        self.assertTrue(matches_organization_filters(org,{"search":"одежда"}))
        self.assertFalse(matches_organization_filters(org,{"search":"автосервис"}))


if __name__ == "__main__":
    unittest.main()


class CityFilterTests(unittest.TestCase):
    def test_empty_city_selection_means_all_configured_settlements(self):
        org = {"name": "A", "city_name": "Самара"}
        self.assertTrue(matches_organization_filters(org, {"city_names": set()}))

    def test_city_filter_is_multi_select_and_case_insensitive(self):
        org_a = {"name": "A", "city_name": "Самара"}
        org_b = {"name": "B", "city_name": "Тольятти"}
        filters = {"city_names": {"самара", "Тольятти"}}
        self.assertTrue(matches_organization_filters(org_a, filters))
        self.assertTrue(matches_organization_filters(org_b, filters))
        self.assertFalse(matches_organization_filters({"name": "C", "city_name": "Сызрань"}, filters))

    def test_city_filter_combines_with_other_filters(self):
        org = {"name": "Quest", "city_name": "Самара", "category": "Квесты", "status": "Новый"}
        self.assertTrue(matches_organization_filters(org, {"city_names": {"Самара"}, "category": "Квесты"}))
        self.assertFalse(matches_organization_filters(org, {"city_names": {"Тольятти"}, "category": "Квесты"}))


class ExclusionPrecedenceTests(unittest.TestCase):
    def test_excluded_category_wins_over_included_category(self):
        org={"category":"Развлечения","subcategory":"Центр развития ребёнка","categories_json":"[\"Развлечения\",\"Центр развития ребёнка\"]"}
        self.assertTrue(excluded_category_match(org,["Центр развития ребёнка"]))


class CategoryExclusionNormalizationTests(unittest.TestCase):
    def test_official_booking_categories_are_available(self):
        from yabiztracker.domain.categories import YANDEX_ACTIVITIES
        values={v for group in YANDEX_ACTIVITIES.values() for v in group.split("|")}
        normalized={" ".join(v.replace("ё","е").replace("Ё","Е").split()).casefold() for v in values}
        for expected in (
            "Дополнительное образование",
            "Центр развития ребёнка",
            "Центр повышения квалификации",
            "Курсы иностранных языков",
            "Услуги репетиторов",
            "Спортивно-развлекательный центр",
        ):
            self.assertIn(" ".join(expected.replace("ё","е").split()).casefold(), normalized)

    def test_yo_and_e_are_treated_as_the_same_category(self):
        org={"category":"Дополнительное образование","categories_json":"[\"Дополнительное образование\", \"Центр развития ребёнка\"]"}
        self.assertTrue(excluded_category_match(org,["Центр развития ребенка"]))

    def test_exclusion_matches_legacy_category_spelling(self):
        org={"category":"Дополнительное образование","categories_json":"[\"Дополнительное образование\", \"Центр развития ребенка\"]"}
        self.assertTrue(excluded_category_match(org,["Центр развития ребёнка"]))

class PhoneLinkTests(unittest.TestCase):
    def test_russian_phone_formats_normalize_at_integration_boundary(self):
        from yabiztracker.domain.phone import normalize_ru_phone
        self.assertEqual(normalize_ru_phone("8 (999) 999-99-99"), "+79999999999")
        self.assertEqual(normalize_ru_phone("+7 (999) 999-99-99"), "+79999999999")
        self.assertEqual(normalize_ru_phone("89999999999"), "+79999999999")
        self.assertEqual(normalize_ru_phone("9999999999"), "+79999999999")

    def test_invalid_phone_does_not_produce_messenger_link(self):
        from yabiztracker.domain.phone import messenger_url
        self.assertIsNone(messenger_url("Telegram", "12345"))

    def test_messenger_url_templates(self):
        from yabiztracker.domain.phone import messenger_url
        phone = "8 (999) 999-99-99"
        self.assertEqual(messenger_url("Telegram", phone), "https://t.me/+79999999999")
        self.assertEqual(messenger_url("WhatsApp", phone), "https://wa.me/+79999999999")
        self.assertEqual(messenger_url("Viber", phone), "https://viber.click/79999999999")
        self.assertEqual(messenger_url("Max", phone), "https://max.ru/+79999999999")

    def test_multiple_phone_values_are_split_and_deduplicated(self):
        from yabiztracker.domain.phone import split_phone_values
        self.assertEqual(
            split_phone_values("8 (999) 999-99-99, +7 (900) 000-00-00; 8 (999) 999-99-99"),
            ["8 (999) 999-99-99", "+7 (900) 000-00-00"],
        )


class SelectionEdgeCaseTests(unittest.TestCase):
    def test_shift_range_with_single_visible_row(self):
        self.assertEqual(visible_range([4], 4, 4), [4])

    def test_shift_range_uses_visual_order_after_filtering(self):
        visible = [1, 4, 7, 9]
        self.assertEqual(visible_range(visible, 4, 9), [4, 7, 9])
        self.assertEqual(visible_range(visible, 9, 1), [1, 4, 7, 9])

    def test_invalid_target_never_selects_anything(self):
        self.assertEqual(visible_range([1, 3, 5], 1, 4), [])
