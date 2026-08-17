import json
import pathlib
import unittest
from typing import Dict, List

from wox_plugin import Context, MetadataCommand, PluginInitParams, Query, QueryEnv, QueryType, Selection

from src.main import KagiPlugin
from src.settings import enabled_key, keyword_key

ROOT = pathlib.Path(__file__).resolve().parent.parent


def manifest_defaults() -> Dict[str, str]:
    """The values Wox seeds a fresh install with, taken from plugin.json."""

    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    return {
        item["Value"]["Key"]: item["Value"].get("DefaultValue", "") for item in manifest["SettingDefinitions"] if "Key" in item["Value"]
    }


class FakeAPI:
    """Just enough of the Wox PublicAPI for the query paths under test."""

    def __init__(self, settings: Dict[str, str]) -> None:
        self.settings = settings
        self.registered_commands: List[MetadataCommand] = []
        self.logs: List[str] = []
        self.copied: List[str] = []
        self.notifications: List[str] = []
        self.queries: List[str] = []
        self.setting_callback = None

    async def get_setting(self, ctx, key: str) -> str:
        return self.settings.get(key, "")

    async def save_setting(self, ctx, key: str, value: str, is_platform_specific: bool) -> None:
        self.settings[key] = value

    async def on_setting_changed(self, ctx, callback) -> None:
        self.setting_callback = callback

    async def register_query_commands(self, ctx, commands) -> None:
        self.registered_commands = list(commands)

    async def log(self, ctx, level, msg: str) -> None:
        self.logs.append(msg)

    async def copy(self, ctx, params) -> None:
        self.copied.append(params.text)

    async def notify(self, ctx, message: str) -> None:
        self.notifications.append(message)

    async def change_query(self, ctx, query) -> None:
        self.queries.append(query.query_text)


def make_query(search: str, command: str = "", trigger_keyword: str = "kagi") -> Query:
    return Query(
        id="test",
        type=QueryType.INPUT,
        raw_query=f"{trigger_keyword} {command} {search}".strip(),
        selection=Selection(),
        env=QueryEnv(),
        trigger_keyword=trigger_keyword,
        command=command,
        search=search,
    )


class KagiPluginTestCase(unittest.IsolatedAsyncioTestCase):
    settings: Dict[str, str] = {}
    suggestions: List[str] = []

    async def asyncSetUp(self) -> None:
        self.ctx = Context.new()
        self.api = FakeAPI({**manifest_defaults(), **self.settings})
        self.plugin = KagiPlugin()
        await self.plugin.init(self.ctx, PluginInitParams(api=self.api, plugin_directory="."))

        self.suggest_calls: List[str] = []
        suggestions = list(self.suggestions)

        async def fake_autosuggest(term: str, limit: int) -> List[str]:
            self.suggest_calls.append(term)
            return suggestions[:limit]

        self.plugin.client.autosuggest = fake_autosuggest  # type: ignore[method-assign]

    def urls_of(self, results) -> List[str]:
        return [result.actions[0].context_data.get("url", "") for result in results if result.actions]


class TestCommandRegistration(KagiPluginTestCase):
    async def test_registers_one_command_per_keyword(self):
        commands = {command.command for command in self.api.registered_commands}

        self.assertIn("img", commands)
        self.assertIn("news", commands)
        self.assertNotIn("", commands)

    async def test_disabling_a_service_removes_its_command(self):
        self.api.settings[enabled_key(self.plugin.settings.config("images").service)] = "false"
        await self.api.setting_callback(self.ctx, "service_images_enabled", "false")

        commands = {command.command for command in self.api.registered_commands}
        self.assertNotIn("img", commands)


class TestWebSearch(KagiPluginTestCase):
    suggestions = ["red pandas eat", "red pandas facts"]

    async def test_unprefixed_query_falls_back_to_web_search(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(results[0].title, "Search Kagi for “red pandas”")
        self.assertEqual(self.urls_of(results)[0], "https://kagi.com/search?q=red+pandas")

    async def test_suggestions_are_listed_below_the_primary_result(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(self.suggest_calls, ["red pandas"])
        titles = [result.title for result in results]
        self.assertIn("red pandas eat", titles)
        self.assertLess(results[1].score, results[0].score)

    async def test_suggestion_opens_the_same_vertical(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))
        suggestion = next(result for result in results if result.title == "red pandas eat")

        self.assertEqual(suggestion.actions[0].context_data["url"], "https://kagi.com/search?q=red+pandas+eat")

    async def test_primary_result_offers_the_other_verticals(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))
        action_names = [action.name for action in results[0].actions]

        self.assertIn("Open in browser", action_names)
        self.assertIn("Copy link", action_names)
        self.assertIn("Open in Image Search", action_names)


class TestCommandRouting(KagiPluginTestCase):
    async def test_command_reported_by_wox(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas", command="img"))

        self.assertEqual(self.urls_of(results)[0], "https://kagi.com/images?q=red+pandas")

    async def test_keyword_typed_inline_is_parsed_by_the_plugin(self):
        results = await self.plugin.query(self.ctx, make_query("vid red pandas"))

        self.assertEqual(self.urls_of(results)[0], "https://kagi.com/videos?q=red+pandas")

    async def test_unknown_first_word_stays_a_web_search(self):
        results = await self.plugin.query(self.ctx, make_query("pandas red"))

        self.assertEqual(self.urls_of(results)[0], "https://kagi.com/search?q=pandas+red")

    async def test_custom_keyword_is_honoured(self):
        self.api.settings[keyword_key(self.plugin.settings.config("news").service)] = "n"
        await self.api.setting_callback(self.ctx, "service_news_keyword", "n")

        results = await self.plugin.query(self.ctx, make_query("n budget"))
        self.assertEqual(self.urls_of(results)[0], "https://kagi.com/news?q=budget")

        stale = await self.plugin.query(self.ctx, make_query("news budget"))
        self.assertEqual(self.urls_of(stale)[0], "https://kagi.com/search?q=news+budget")


class TestOtherServices(KagiPluginTestCase):
    async def test_translate_uses_the_configured_languages(self):
        results = await self.plugin.query(self.ctx, make_query("hello", command="tr"))
        url = self.urls_of(results)[0]

        self.assertIn("text=hello", url)
        self.assertIn("from=auto", url)
        self.assertIn("to=en", url)
        self.assertEqual(results[0].title, "Translate “hello” into en")

    async def test_translate_accepts_a_per_query_language(self):
        results = await self.plugin.query(self.ctx, make_query("hello > fr", command="tr"))
        url = self.urls_of(results)[0]

        self.assertIn("text=hello", url)
        self.assertIn("to=fr", url)

    async def test_launch_service_opens_without_a_term(self):
        results = await self.plugin.query(self.ctx, make_query("", command="kite"))

        self.assertEqual(results[0].title, "Open Kagi News")
        self.assertEqual(self.urls_of(results)[0], "https://news.kagi.com/")

    async def test_summarizer_takes_a_url(self):
        results = await self.plugin.query(self.ctx, make_query("https://example.com", command="sum"))

        self.assertEqual(self.urls_of(results)[0], "https://kagi.com/summarizer?url=https%3A%2F%2Fexample.com")

    async def test_no_suggestions_for_non_search_services(self):
        await self.plugin.query(self.ctx, make_query("hello", command="tr"))

        self.assertEqual(self.suggest_calls, [])


class TestServiceMenu(KagiPluginTestCase):
    async def test_empty_query_lists_the_services(self):
        results = await self.plugin.query(self.ctx, make_query(""))
        titles = [result.title for result in results]

        self.assertIn("Image Search", titles)
        self.assertIn("Universal Summarizer", titles)

    async def test_command_without_a_term_prompts_for_input(self):
        results = await self.plugin.query(self.ctx, make_query("", command="sum"))

        self.assertEqual(results[0].title, "Universal Summarizer: type a URL")

    async def test_picking_a_service_rewrites_the_search_box(self):
        results = await self.plugin.query(self.ctx, make_query(""))
        images = next(result for result in results if result.title == "Image Search")

        await images.actions[0].action(self.ctx, _action_context(images.actions[0]))
        self.assertEqual(self.api.queries, ["kagi img "])


class TestActions(KagiPluginTestCase):
    async def test_copy_link_puts_the_url_on_the_clipboard(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))
        copy_action = next(action for action in results[0].actions if action.name == "Copy link")

        await copy_action.action(self.ctx, _action_context(copy_action))
        self.assertEqual(self.api.copied, ["https://kagi.com/search?q=red+pandas"])


class TestSuggestionsDisabled(KagiPluginTestCase):
    settings = {"suggestions_enabled": "false"}
    suggestions = ["red pandas eat"]

    async def test_no_network_call_when_turned_off(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(self.suggest_calls, [])
        self.assertEqual(len(results), 1)


class TestAllServicesDisabled(KagiPluginTestCase):
    settings = {
        f"service_{key}_enabled": "false"
        for key in (
            "web",
            "images",
            "videos",
            "news",
            "podcasts",
            "maps",
            "assistant",
            "fastgpt",
            "summarize",
            "translate",
            "proofread",
            "dictionary",
            "smallweb",
            "kagi_news",
        )
    }

    async def test_the_user_is_told_what_to_do(self):
        results = await self.plugin.query(self.ctx, make_query("red pandas"))

        self.assertEqual(len(results), 1)
        self.assertIn("Enable at least one", results[0].title)


def _action_context(action):
    from wox_plugin import ActionContext

    return ActionContext(context_data=dict(action.context_data or {}))


if __name__ == "__main__":
    unittest.main()
