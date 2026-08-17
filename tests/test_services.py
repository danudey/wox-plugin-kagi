import unittest

from src.services import SERVICES, SERVICES_BY_KEY, ServiceKind, build_url


class TestServiceCatalog(unittest.TestCase):
    def test_keys_and_keywords_are_unique(self):
        keys = [service.key for service in SERVICES]
        keywords = [service.default_keyword for service in SERVICES if service.default_keyword]

        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keywords), len(set(keywords)))

    def test_web_is_the_only_service_without_a_keyword(self):
        without = [service.key for service in SERVICES if not service.default_keyword]

        self.assertEqual(without, ["web"])

    def test_every_service_points_at_kagi(self):
        for service in SERVICES:
            self.assertRegex(service.base_url, r"^https://[a-z.]*kagi\.com/", service.key)


class TestBuildUrl(unittest.TestCase):
    def test_search_url(self):
        url = build_url(SERVICES_BY_KEY["web"], "red pandas")

        self.assertEqual(url, "https://kagi.com/search?q=red+pandas")

    def test_query_parameter_name_is_per_service(self):
        self.assertEqual(build_url(SERVICES_BY_KEY["fastgpt"], "why"), "https://kagi.com/fastgpt?query=why")
        self.assertEqual(
            build_url(SERVICES_BY_KEY["dictionary"], "serendipity"),
            "https://translate.kagi.com/dictionary?word=serendipity",
        )

    def test_extra_parameters_are_merged(self):
        url = build_url(SERVICES_BY_KEY["translate"], "hello", {"from": "auto", "to": "fr"})

        self.assertIn("text=hello", url)
        self.assertIn("from=auto", url)
        self.assertIn("to=fr", url)

    def test_empty_extra_values_are_dropped(self):
        url = build_url(SERVICES_BY_KEY["translate"], "hello", {"from": "", "to": "fr"})

        self.assertNotIn("from=", url)

    def test_launch_service_ignores_the_term(self):
        smallweb = SERVICES_BY_KEY["smallweb"]

        self.assertIs(smallweb.kind, ServiceKind.LAUNCH)
        self.assertEqual(build_url(smallweb, "anything"), "https://kagi.com/smallweb/")

    def test_no_term_returns_the_bare_product_url(self):
        self.assertEqual(build_url(SERVICES_BY_KEY["images"], "  "), "https://kagi.com/images")

    def test_values_are_url_encoded(self):
        url = build_url(SERVICES_BY_KEY["web"], "a&b c?d")

        self.assertEqual(url, "https://kagi.com/search?q=a%26b+c%3Fd")


if __name__ == "__main__":
    unittest.main()
