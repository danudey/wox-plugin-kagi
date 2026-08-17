import unittest

from src.services import SERVICES
from src.settings import DEFAULTS, build_settings, enabled_key, keyword_key, setting_keys, split_command


class TestBuildSettings(unittest.TestCase):
    def test_defaults_are_applied_when_nothing_is_stored(self):
        settings = build_settings({})

        self.assertEqual(settings.api_key, "")
        self.assertTrue(settings.suggestions_enabled)
        self.assertEqual(settings.suggestions_limit, 6)
        self.assertFalse(settings.api_search_inline)
        self.assertEqual(settings.translate_target, "en")
        self.assertEqual(len(settings.services), len(SERVICES))
        self.assertEqual(settings.warnings, [])

    def test_every_service_is_enabled_with_its_default_keyword(self):
        settings = build_settings({})

        for service in SERVICES:
            config = settings.config(service.key)
            self.assertIsNotNone(config)
            self.assertTrue(config.enabled, service.key)
            self.assertEqual(config.keyword, service.default_keyword, service.key)

    def test_keywords_are_normalised(self):
        settings = build_settings({keyword_key(SERVICES[1]): "  IMG extra  "})

        self.assertEqual(settings.config("images").keyword, "img")

    def test_disabled_service_is_not_matched(self):
        settings = build_settings({enabled_key(SERVICES[1]): "false"})

        self.assertFalse(settings.is_enabled("images"))
        self.assertIsNone(settings.match_keyword("img"))
        self.assertNotIn("images", [config.service.key for config in settings.enabled_services()])

    def test_duplicate_keyword_is_dropped_with_a_warning(self):
        settings = build_settings({keyword_key(SERVICES[2]): "img", keyword_key(SERVICES[1]): "img"})

        matched = settings.match_keyword("img")
        self.assertEqual(matched.service.key, "images")
        self.assertEqual(settings.config("videos").keyword, "")
        self.assertEqual(len(settings.warnings), 1)
        self.assertIn("img", settings.warnings[0])

    def test_match_keyword_ignores_case_and_padding(self):
        settings = build_settings({})

        self.assertEqual(settings.match_keyword("  NEWS ").service.key, "news")
        self.assertIsNone(settings.match_keyword(""))
        self.assertIsNone(settings.match_keyword("nope"))

    def test_numeric_settings_are_clamped(self):
        settings = build_settings({"suggestions_limit": "99", "api_result_limit": "0", "request_timeout": "not a number"})

        self.assertEqual(settings.suggestions_limit, 15)
        self.assertEqual(settings.api_result_limit, 1)
        self.assertEqual(settings.request_timeout, 6.0)

    def test_warning_when_all_services_are_disabled(self):
        values = {enabled_key(service): "false" for service in SERVICES}
        settings = build_settings(values)

        self.assertEqual(settings.enabled_services(), [])
        self.assertTrue(any("disabled" in warning for warning in settings.warnings))

    def test_setting_keys_cover_the_manifest(self):
        keys = setting_keys()

        self.assertEqual(len(keys), len(set(keys)))
        for key in DEFAULTS:
            self.assertIn(key, keys)
        for service in SERVICES:
            self.assertIn(enabled_key(service), keys)
            self.assertIn(keyword_key(service), keys)


class TestSplitCommand(unittest.TestCase):
    def test_splits_the_first_word(self):
        self.assertEqual(split_command("img red pandas"), ("img", "red pandas"))
        self.assertEqual(split_command("  news  "), ("news", ""))
        self.assertEqual(split_command(""), ("", ""))


if __name__ == "__main__":
    unittest.main()
