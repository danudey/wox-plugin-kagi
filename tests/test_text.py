import unittest

from src.text import clean_snippet, format_published, looks_like_url, parse_language_suffix, summary_subtitle


class TestCleanSnippet(unittest.TestCase):
    def test_strips_markup_and_collapses_whitespace(self):
        self.assertEqual(clean_snippet("<b>Red</b>  pandas\nlive here"), "Red pandas live here")

    def test_unescapes_entities(self):
        self.assertEqual(clean_snippet("cats &amp; dogs"), "cats & dogs")

    def test_empty_input(self):
        self.assertEqual(clean_snippet(""), "")


class TestLooksLikeUrl(unittest.TestCase):
    def test_accepts_urls(self):
        for candidate in ("https://example.com", "http://example.com/a/b", "www.example.com", "example.com/page"):
            self.assertTrue(looks_like_url(candidate), candidate)

    def test_rejects_prose(self):
        for candidate in ("summarize this page", "hello", "", "example com"):
            self.assertFalse(looks_like_url(candidate), candidate)


class TestParseLanguageSuffix(unittest.TestCase):
    def test_reads_a_trailing_override(self):
        self.assertEqual(parse_language_suffix("hello world > fr", "en"), ("hello world", "fr"))
        self.assertEqual(parse_language_suffix("hello>PT-BR", "en"), ("hello", "pt-br"))

    def test_falls_back_to_the_default(self):
        self.assertEqual(parse_language_suffix("hello world", "de"), ("hello world", "de"))

    def test_ignores_a_greater_than_in_the_middle(self):
        self.assertEqual(parse_language_suffix("2 > 1 is true", "en"), ("2 > 1 is true", "en"))


class TestFormatPublished(unittest.TestCase):
    def test_keeps_the_date_only(self):
        self.assertEqual(format_published("2026-08-17T10:22:00Z"), "2026-08-17")

    def test_passes_other_formats_through(self):
        self.assertEqual(format_published("last week"), "last week")
        self.assertEqual(format_published(""), "")


class TestSummarySubtitle(unittest.TestCase):
    def test_truncates_long_output(self):
        subtitle = summary_subtitle("word " * 100, limit=20)

        self.assertEqual(len(subtitle), 20)
        self.assertTrue(subtitle.endswith("…"))

    def test_short_output_is_untouched(self):
        self.assertEqual(summary_subtitle("all done"), "all done")


if __name__ == "__main__":
    unittest.main()
