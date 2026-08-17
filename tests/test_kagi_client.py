import io
import json
import unittest
import urllib.error
from typing import Any, Dict, List

from src import kagi_client
from src.kagi_client import KagiClient, KagiError, _coerce_items, _http_error_detail, _TTLCache


class RecordingTransport:
    """Stands in for `_read_json`, recording the calls the client makes."""

    def __init__(self, responses: List[Any]) -> None:
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url, headers, timeout, data=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout, "data": data})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ClientTestCase(unittest.IsolatedAsyncioTestCase):
    def install(self, *responses: Any) -> RecordingTransport:
        transport = RecordingTransport(list(responses))
        self.addCleanup(setattr, kagi_client, "_read_json", kagi_client._read_json)
        kagi_client._read_json = transport
        return transport


class TestAutosuggest(ClientTestCase):
    async def test_parses_the_opensearch_format(self):
        transport = self.install(["red", ["red pandas", "red wine"]])
        client = KagiClient()

        self.assertEqual(await client.autosuggest("red", 5), ["red pandas", "red wine"])
        self.assertIn("kagisuggest.com", transport.calls[0]["url"])
        self.assertIn("q=red", transport.calls[0]["url"])

    async def test_needs_no_api_key(self):
        transport = self.install(["red", ["red pandas"]])

        await KagiClient().autosuggest("red", 5)
        self.assertNotIn("Authorization", transport.calls[0]["headers"])

    async def test_honours_the_limit_and_drops_the_echoed_term(self):
        self.install(["red", ["red", "red pandas", "red wine", "red sky"]])

        self.assertEqual(await KagiClient().autosuggest("red", 2), ["red pandas", "red wine"])

    async def test_repeated_terms_are_served_from_cache(self):
        transport = self.install(["red", ["red pandas"]])
        client = KagiClient()

        await client.autosuggest("red", 5)
        await client.autosuggest("red", 5)

        self.assertEqual(len(transport.calls), 1)

    async def test_empty_term_never_hits_the_network(self):
        transport = self.install()

        self.assertEqual(await KagiClient().autosuggest("   ", 5), [])
        self.assertEqual(transport.calls, [])

    async def test_unexpected_payload_yields_no_suggestions(self):
        self.install({"not": "a list"})

        self.assertEqual(await KagiClient().autosuggest("red", 5), [])


class TestSearch(ClientTestCase):
    payload = {
        "data": [
            {"t": 0, "url": "https://a.example", "title": "A", "snippet": "<b>A</b>"},
            {"t": 1, "list": ["related"]},
            {"t": 0, "url": "https://b.example", "title": "B"},
        ]
    }

    async def test_uses_the_v1_endpoint_with_bot_auth(self):
        transport = self.install(self.payload)

        items = await KagiClient("key").search("red pandas", 5)

        self.assertEqual([item.title for item in items], ["A", "B"])
        self.assertEqual(transport.calls[0]["url"], "https://kagi.com/api/v1/search")
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], "Bot key")
        self.assertEqual(json.loads(transport.calls[0]["data"]), {"q": "red pandas", "limit": 5})

    async def test_falls_back_to_v0_when_v1_fails(self):
        transport = self.install(KagiError("boom"), self.payload)

        items = await KagiClient("key").search("red pandas", 5)

        self.assertEqual(len(items), 2)
        self.assertIn("/v0/search?", transport.calls[1]["url"])

    async def test_without_a_key_the_call_is_refused(self):
        self.install(self.payload)

        with self.assertRaises(KagiError):
            await KagiClient().search("red pandas", 5)

    async def test_results_are_cached_per_term(self):
        transport = self.install(self.payload)
        client = KagiClient("key")

        await client.search("red pandas", 5)
        await client.search("red pandas", 5)

        self.assertEqual(len(transport.calls), 1)

    async def test_changing_the_key_clears_cached_answers(self):
        transport = self.install(self.payload, self.payload)
        client = KagiClient("key")

        await client.search("red pandas", 5)
        client.configure("other", 6.0)
        await client.search("red pandas", 5)

        self.assertEqual(len(transport.calls), 2)


class TestGeneratedAnswers(ClientTestCase):
    async def test_fastgpt_returns_output_and_references(self):
        transport = self.install(
            {
                "data": {
                    "output": "Because.",
                    "references": [{"title": "Ref", "url": "https://ref.example", "snippet": "s"}],
                }
            }
        )

        answer = await KagiClient("key").fastgpt("why")

        self.assertEqual(answer.output, "Because.")
        self.assertEqual(answer.references[0].url, "https://ref.example")
        self.assertEqual(transport.calls[0]["url"], "https://kagi.com/api/v0/fastgpt")

    async def test_summarize_sends_the_configured_options(self):
        transport = self.install({"data": {"output": "Short version."}})

        answer = await KagiClient("key").summarize("https://example.com", engine="agnes", summary_type="takeaway", target_language="FR")

        self.assertEqual(answer.output, "Short version.")
        body = json.loads(transport.calls[0]["data"])
        self.assertEqual(body["url"], "https://example.com")
        self.assertEqual(body["engine"], "agnes")
        self.assertEqual(body["summary_type"], "takeaway")
        self.assertEqual(body["target_language"], "FR")

    async def test_summarize_can_take_raw_text(self):
        transport = self.install({"data": {"output": "Short version."}})

        await KagiClient("key").summarize("a long piece of prose", is_url=False)

        self.assertIn("text", json.loads(transport.calls[0]["data"]))

    async def test_missing_data_is_an_error(self):
        self.install({"meta": {}})

        with self.assertRaises(KagiError):
            await KagiClient("key").fastgpt("why")


class TestEnrich(ClientTestCase):
    async def test_news_index(self):
        transport = self.install({"data": [{"t": 0, "url": "https://n.example", "title": "N"}]})

        items = await KagiClient("key").enrich("news", "budget", 3)

        self.assertEqual(items[0].title, "N")
        self.assertIn("/v0/enrich/news?", transport.calls[0]["url"])


class TestCoerceItems(unittest.TestCase):
    def test_reads_a_nested_results_key(self):
        items = _coerce_items({"results": [{"url": "https://a.example", "title": "A"}]})

        self.assertEqual(len(items), 1)

    def test_entries_without_a_url_or_title_are_skipped(self):
        items = _coerce_items([{"url": "https://a.example"}, {"title": "A"}, "junk"])

        self.assertEqual(items, [])

    def test_description_is_used_when_there_is_no_snippet(self):
        items = _coerce_items([{"url": "https://a.example", "title": "A", "description": "d"}])

        self.assertEqual(items[0].snippet, "d")

    def test_unusable_payloads_return_nothing(self):
        self.assertEqual(_coerce_items(None), [])
        self.assertEqual(_coerce_items({"meta": {}}), [])


class TestErrorDetail(unittest.TestCase):
    def _error(self, body: str) -> urllib.error.HTTPError:
        return urllib.error.HTTPError("https://kagi.com/api/v0/search", 401, "Unauthorized", {}, io.BytesIO(body.encode("utf-8")))

    def test_reads_the_v0_error_shape(self):
        detail = _http_error_detail(self._error('{"error":[{"code":2,"msg":"Malformed authorization token"}]}'))

        self.assertEqual(detail, ": Malformed authorization token")

    def test_reads_the_v1_error_shape(self):
        detail = _http_error_detail(self._error('{"errors":[{"message":"Unauthorized"}]}'))

        self.assertEqual(detail, ": Unauthorized")

    def test_unparsable_bodies_are_ignored(self):
        self.assertEqual(_http_error_detail(self._error("<html>nope</html>")), "")


class TestTTLCache(unittest.TestCase):
    def test_expired_entries_are_dropped(self):
        cache = _TTLCache(ttl_seconds=-1.0)
        cache.set("k", "v")

        self.assertIsNone(cache.get("k"))

    def test_the_cache_is_bounded(self):
        cache = _TTLCache(ttl_seconds=60.0, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)

        self.assertLessEqual(len(cache._entries), 2)
        self.assertEqual(cache.get("c"), 3)


if __name__ == "__main__":
    unittest.main()
