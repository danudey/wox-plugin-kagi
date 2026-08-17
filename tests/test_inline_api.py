"""The optional, paid API paths: they must stay off until the user opts in."""

import unittest
from typing import List

from src.kagi_client import Answer, KagiError, SearchItem
from tests.test_query import KagiPluginTestCase, make_query

ITEMS = [
    SearchItem(title="Red panda", url="https://a.example", snippet="<b>Red</b> pandas &amp; more", published="2026-08-17T10:00:00Z"),
    SearchItem(title="Panda facts", url="https://b.example", snippet="Facts"),
]


class InlineTestCase(KagiPluginTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.search_calls: List[str] = []
        self.enrich_calls: List[str] = []
        self.fastgpt_calls: List[str] = []
        self.summarize_calls: List[str] = []

        async def search(term, limit):
            self.search_calls.append(term)
            return ITEMS[:limit]

        async def enrich(index, term, limit):
            self.enrich_calls.append(f"{index}:{term}")
            return ITEMS[:limit]

        async def fastgpt(question):
            self.fastgpt_calls.append(question)
            return Answer(output="Because they are.", references=[ITEMS[0]])

        async def summarize(target, **kwargs):
            self.summarize_calls.append(target)
            return Answer(output="The short version.")

        self.plugin.client.search = search
        self.plugin.client.enrich = enrich
        self.plugin.client.fastgpt = fastgpt
        self.plugin.client.summarize = summarize


class TestPaidCallsAreOptIn(InlineTestCase):
    settings = {"api_key": "secret"}

    async def test_a_key_alone_does_not_spend_credit(self):
        await self.plugin.query(self.ctx, make_query("red pandas"))
        await self.plugin.query(self.ctx, make_query("why", command="gpt"))
        await self.plugin.query(self.ctx, make_query("https://example.com", command="sum"))

        self.assertEqual(self.search_calls, [])
        self.assertEqual(self.fastgpt_calls, [])
        self.assertEqual(self.summarize_calls, [])


class TestNoApiKey(InlineTestCase):
    settings = {"api_search_inline": "true", "api_fastgpt_inline": "true"}

    async def test_inline_results_need_a_key(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(self.search_calls, [])
        self.assertEqual(results[0].title, "Search Kagi for “red pandas”")


class TestInlineSearch(InlineTestCase):
    settings = {"api_key": "secret", "api_search_inline": "true", "suggestions_enabled": "false"}

    async def test_web_results_are_listed(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(self.search_calls, ["red pandas"])
        titles = [result.title for result in results]
        self.assertIn("Red panda", titles)

    async def test_snippets_are_cleaned_and_dates_shown(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))
        item = next(result for result in results if result.title == "Red panda")

        self.assertEqual(item.sub_title, "Red pandas & more")
        self.assertEqual(item.tails[0].text, "2026-08-17")

    async def test_a_result_can_be_sent_to_the_summarizer(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))
        item = next(result for result in results if result.title == "Red panda")
        names = [action.name for action in item.actions]

        self.assertIn("Summarize this page", names)

    async def test_news_uses_the_enrichment_index(self):
        await self.plugin.query(self.ctx, make_query("budget", command="news"))

        self.assertEqual(self.enrich_calls, ["news:budget"])
        self.assertEqual(self.search_calls, [])

    async def test_small_web_uses_the_web_index(self):
        await self.plugin.query(self.ctx, make_query("gardening", command="small"))

        self.assertEqual(self.enrich_calls, ["web:gardening"])

    async def test_verticals_without_an_api_stay_link_only(self):
        await self.plugin.query(self.ctx, make_query("red pandas", command="img"))

        self.assertEqual(self.search_calls, [])
        self.assertEqual(self.enrich_calls, [])


class TestInlineAnswers(InlineTestCase):
    settings = {
        "api_key": "secret",
        "api_fastgpt_inline": "true",
        "api_summarizer_inline": "true",
        "summarizer_engine": "agnes",
    }

    async def test_quick_answer_is_shown_and_copyable(self):
        results = await self.plugin.query(self.ctx, make_query("why is the sky blue", command="gpt"))

        self.assertEqual(self.fastgpt_calls, ["why is the sky blue"])
        answer = results[1]
        self.assertEqual(answer.title, "Because they are.")
        self.assertEqual(answer.preview.preview_data, "Because they are.")
        self.assertEqual(answer.actions[0].name, "Copy answer")

    async def test_quick_answer_lists_its_sources(self):
        results = await self.plugin.query(self.ctx, make_query("why", command="gpt"))
        groups = {result.group for result in results}

        self.assertIn("Sources", groups)

    async def test_summaries_are_shown(self):
        results = await self.plugin.query(self.ctx, make_query("https://example.com", command="sum"))

        self.assertEqual(self.summarize_calls, ["https://example.com"])
        self.assertEqual(results[1].title, "The short version.")


class TestApiFailures(InlineTestCase):
    settings = {"api_key": "secret", "api_search_inline": "true", "suggestions_enabled": "false"}

    async def test_a_failure_is_reported_without_losing_the_link(self):
        async def failing_search(term, limit):
            raise KagiError("Kagi returned HTTP 401: Malformed authorization token")

        self.plugin.client.search = failing_search

        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(results[0].title, "Search Kagi for “red pandas”")
        self.assertIn("401", results[1].title)
        self.assertTrue(self.api.logs)


if __name__ == "__main__":
    unittest.main()
