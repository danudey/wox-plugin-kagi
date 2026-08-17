"""Kagi for Wox.

Drives Kagi's search verticals and standalone products from the Wox launcher,
with free autocomplete suggestions and optional inline answers from the paid
Kagi APIs.
"""

from __future__ import annotations

import asyncio
import webbrowser
from typing import List, Optional, Tuple

from wox_plugin import (
    ActionContext,
    ChangeQueryParam,
    Context,
    CopyParams,
    CopyType,
    LogLevel,
    MetadataCommand,
    Plugin,
    PluginInitParams,
    PublicAPI,
    Query,
    QueryType,
    Result,
    ResultAction,
    ResultTail,
    ResultTailType,
    WoxImage,
    WoxPreview,
    WoxPreviewType,
)

from kagi_client import Answer, KagiClient, KagiError, SearchItem
from services import SERVICES_BY_KEY, Service, ServiceKind, build_url
from settings import PluginSettings, ServiceConfig, load_settings, split_command
from text import (
    clean_snippet,
    format_published,
    looks_like_url,
    parse_language_suffix,
    quoted,
    summary_subtitle,
)

PLUGIN_ICON = "images/app.svg"
OPEN_ICON = "icons/open.svg"
COPY_ICON = "icons/copy.svg"
WARNING_ICON = "icons/search.svg"

# Scores are spread out so the primary result always sorts above suggestions,
# which in turn sort above the cross service shortcuts.
SCORE_PRIMARY = 100.0
SCORE_ANSWER = 95.0
SCORE_API_RESULT = 80.0
SCORE_SUGGESTION = 60.0
SCORE_MENU = 40.0
SCORE_WARNING = 10.0


def _icon(path: str) -> WoxImage:
    return WoxImage.new_relative(path)


class KagiPlugin(Plugin):
    """Wox plugin entry point."""

    def __init__(self) -> None:
        self.api: Optional[PublicAPI] = None
        self.client = KagiClient()
        self.settings = PluginSettings()
        self.trigger_keyword = "kagi"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self, ctx: Context, init_params: PluginInitParams) -> None:
        self.api = init_params.api
        await self._reload_settings(ctx)
        await self.api.on_setting_changed(ctx, self._on_setting_changed)

    async def _on_setting_changed(self, ctx: Context, key: str, value: str) -> None:
        await self._reload_settings(ctx)

    async def _reload_settings(self, ctx: Context) -> None:
        """Re-read settings, then re-register the commands Wox should autocomplete."""

        assert self.api is not None
        api = self.api

        async def read(key: str) -> str:
            return await api.get_setting(ctx, key)

        self.settings = await load_settings(read)
        self.client.configure(self.settings.api_key, self.settings.request_timeout)

        commands = [
            MetadataCommand(command=config.keyword, description=config.service.description)
            for config in self.settings.enabled_services()
            if config.keyword
        ]

        try:
            await api.register_query_commands(ctx, commands)
        except Exception as error:  # pragma: no cover - depends on the Wox host
            await self._log(ctx, LogLevel.WARNING, f"Could not register query commands: {error}")

        for warning in self.settings.warnings:
            await self._log(ctx, LogLevel.WARNING, warning)

    async def _log(self, ctx: Context, level: LogLevel, message: str) -> None:
        if self.api is None:
            return
        try:
            await self.api.log(ctx, level, message)
        except Exception:  # pragma: no cover - logging must never break a query
            pass

    # ------------------------------------------------------------------
    # Query handling
    # ------------------------------------------------------------------

    async def query(self, ctx: Context, query: Query) -> List[Result]:
        if query.trigger_keyword:
            self.trigger_keyword = query.trigger_keyword

        config, term = self._resolve(query)

        results: List[Result] = []
        if config is None:
            results.extend(self._service_menu(""))
        elif not term and config.service.kind is not ServiceKind.LAUNCH:
            results.append(self._prompt_result(config))
            results.extend(self._service_menu("", exclude=config.service.key))
        else:
            results.append(self._primary_result(config, term))
            results.extend(await self._inline_results(ctx, config, term))
            results.extend(await self._suggestion_results(ctx, config, term))

        results.extend(self._warning_results())
        return results

    def _resolve(self, query: Query) -> Tuple[Optional[ServiceConfig], str]:
        """Work out which service the user is addressing and what they typed."""

        search = (query.search or "").strip()

        # Wox strips a registered command out of `search` and reports it separately.
        if query.command:
            config = self.settings.match_keyword(query.command)
            if config is not None:
                return config, search

        # Commands are registered at runtime, so also parse the first word here.
        # This keeps the plugin usable before Wox has picked the commands up.
        head, tail = split_command(search)
        config = self.settings.match_keyword(head)
        if config is not None:
            return config, tail

        web = self.settings.config("web")
        if web is not None and web.enabled:
            return web, search

        enabled = self.settings.enabled_services()
        return (enabled[0], search) if enabled else (None, search)

    # ------------------------------------------------------------------
    # Result builders
    # ------------------------------------------------------------------

    def _target_url(self, config: ServiceConfig, term: str) -> str:
        service = config.service

        if service.key == "translate":
            text, target = parse_language_suffix(term, self.settings.translate_target)
            return build_url(service, text, {"from": self.settings.translate_source, "to": target})

        if service.key == "proofread":
            text, _ = parse_language_suffix(term, "")
            return build_url(service, text)

        return build_url(service, term)

    def _title_for(self, config: ServiceConfig, term: str) -> str:
        service = config.service

        if service.kind is ServiceKind.LAUNCH or not term:
            return f"Open {service.name}"

        if service.kind is ServiceKind.URL:
            return f"Summarize {term}"

        if service.key == "translate":
            text, target = parse_language_suffix(term, self.settings.translate_target)
            return f"Translate {quoted(text)} into {target}"

        if service.kind is ServiceKind.TEXT:
            return f"{service.name}: {quoted(term)}"

        return f"Search {service.search_label or service.name} for {quoted(term)}"

    def _primary_result(self, config: ServiceConfig, term: str) -> Result:
        url = self._target_url(config, term)
        return Result(
            title=self._title_for(config, term),
            sub_title=config.service.description,
            icon=_icon(config.service.icon),
            score=SCORE_PRIMARY,
            actions=self._url_actions(url, extra=self._cross_service_actions(config, term)),
        )

    def _prompt_result(self, config: ServiceConfig) -> Result:
        service = config.service
        return Result(
            title=f"{service.name}: type a {service.placeholder}",
            sub_title=service.description,
            icon=_icon(service.icon),
            score=SCORE_PRIMARY,
            actions=self._url_actions(build_url(service)),
        )

    def _service_menu(self, term: str, exclude: str = "") -> List[Result]:
        """List every enabled service so the user can pick one."""

        results: List[Result] = []
        enabled = [config for config in self.settings.enabled_services() if config.service.key != exclude]

        for index, config in enumerate(enabled):
            service = config.service
            prefix = f"{self.trigger_keyword} {config.keyword}".strip()
            subtitle = f"{service.description} — type: {prefix} " if config.keyword else service.description

            results.append(
                Result(
                    title=service.name,
                    sub_title=subtitle,
                    icon=_icon(service.icon),
                    group="Kagi services",
                    group_score=SCORE_MENU,
                    score=SCORE_MENU - index,
                    tails=[ResultTail(type=ResultTailType.TEXT, text=config.keyword)] if config.keyword else [],
                    actions=self._menu_actions(config, term),
                )
            )

        return results

    def _warning_results(self) -> List[Result]:
        return [
            Result(
                title=warning,
                sub_title="Kagi plugin settings",
                icon=_icon(WARNING_ICON),
                score=SCORE_WARNING,
            )
            for warning in self.settings.warnings
        ]

    async def _suggestion_results(self, ctx: Context, config: ServiceConfig, term: str) -> List[Result]:
        if not self.settings.suggestions_enabled or not config.service.supports_suggestions or not term:
            return []

        try:
            suggestions = await self.client.autosuggest(term, self.settings.suggestions_limit)
        except KagiError as error:
            await self._log(ctx, LogLevel.WARNING, f"Autocomplete failed: {error}")
            return []

        results: List[Result] = []
        for index, suggestion in enumerate(suggestions):
            url = self._target_url(config, suggestion)
            results.append(
                Result(
                    title=suggestion,
                    sub_title=f"Search {config.service.search_label or config.service.name}",
                    icon=_icon(config.service.icon),
                    score=SCORE_SUGGESTION - index,
                    tails=[ResultTail(type=ResultTailType.TEXT, text="suggestion")],
                    actions=self._url_actions(url, extra=[self._refine_action(config, suggestion)]),
                )
            )

        return results

    async def _inline_results(self, ctx: Context, config: ServiceConfig, term: str) -> List[Result]:
        """Fetch answers from the paid APIs, when the user has opted in."""

        capability = config.service.api_capability
        if not capability or not self.settings.has_api_key:
            return []

        try:
            if capability in ("search", "news") and self.settings.api_search_inline:
                items = await self._fetch_search(capability, term)
                return self._search_item_results(items)

            if capability == "smallweb" and self.settings.api_search_inline and term:
                items = await self.client.enrich("web", term, self.settings.api_result_limit)
                return self._search_item_results(items)

            if capability == "fastgpt" and self.settings.api_fastgpt_inline:
                answer = await self.client.fastgpt(term)
                return self._answer_results(answer, "Quick Answer")

            if capability == "summarize" and self.settings.api_summarizer_inline:
                answer = await self.client.summarize(
                    term,
                    engine=self.settings.summarizer_engine,
                    summary_type=self.settings.summarizer_type,
                    target_language=self.settings.summarizer_language,
                    is_url=looks_like_url(term),
                )
                return self._answer_results(answer, "Summary")
        except KagiError as error:
            await self._log(ctx, LogLevel.ERROR, f"Kagi API call failed: {error}")
            return [
                Result(
                    title=str(error),
                    sub_title="Kagi API — check your API key and credit balance",
                    icon=_icon(WARNING_ICON),
                    score=SCORE_API_RESULT,
                )
            ]

        return []

    async def _fetch_search(self, capability: str, term: str) -> List[SearchItem]:
        limit = self.settings.api_result_limit
        if capability == "news":
            return await self.client.enrich("news", term, limit)
        return await self.client.search(term, limit)

    def _search_item_results(self, items: List[SearchItem]) -> List[Result]:
        results: List[Result] = []

        for index, item in enumerate(items):
            tails: List[ResultTail] = []
            published = format_published(item.published)
            if published:
                tails.append(ResultTail(type=ResultTailType.TEXT, text=published))

            results.append(
                Result(
                    title=item.title,
                    sub_title=clean_snippet(item.snippet) or item.url,
                    icon=_icon(PLUGIN_ICON),
                    score=SCORE_API_RESULT - index,
                    group="Results from Kagi",
                    group_score=SCORE_API_RESULT,
                    tails=tails,
                    preview=WoxPreview(
                        preview_type=WoxPreviewType.MARKDOWN,
                        preview_data=f"### {item.title}\n\n{clean_snippet(item.snippet)}\n\n<{item.url}>",
                    ),
                    actions=self._url_actions(item.url, extra=self._summarize_action(item.url)),
                )
            )

        return results

    def _answer_results(self, answer: Answer, label: str) -> List[Result]:
        if not answer.output:
            return []

        results = [
            Result(
                title=summary_subtitle(answer.output),
                sub_title=f"{label} from Kagi — press Enter to copy",
                icon=_icon(PLUGIN_ICON),
                score=SCORE_ANSWER,
                preview=WoxPreview(preview_type=WoxPreviewType.MARKDOWN, preview_data=answer.output),
                actions=[
                    ResultAction(
                        name="Copy answer",
                        icon=_icon(COPY_ICON),
                        is_default=True,
                        context_data={"text": answer.output},
                        action=self._copy_action,
                    )
                ],
            )
        ]

        for index, reference in enumerate(answer.references):
            results.append(
                Result(
                    title=reference.title,
                    sub_title=clean_snippet(reference.snippet) or reference.url,
                    icon=_icon(PLUGIN_ICON),
                    score=SCORE_API_RESULT - index,
                    group="Sources",
                    group_score=SCORE_API_RESULT,
                    actions=self._url_actions(reference.url),
                )
            )

        return results

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _url_actions(self, url: str, extra: Optional[List[ResultAction]] = None) -> List[ResultAction]:
        actions = [
            ResultAction(
                name="Open in browser",
                icon=_icon(OPEN_ICON),
                is_default=True,
                context_data={"url": url},
                action=self._open_action,
            ),
            ResultAction(
                name="Copy link",
                icon=_icon(COPY_ICON),
                context_data={"text": url},
                action=self._copy_action,
            ),
        ]
        actions.extend(extra or [])
        return actions

    def _cross_service_actions(self, config: ServiceConfig, term: str) -> List[ResultAction]:
        """Offer the same term in the other enabled search verticals."""

        if config.service.kind is not ServiceKind.SEARCH or not term:
            return []

        actions: List[ResultAction] = []
        for other in self.settings.enabled_services():
            if other.service.key == config.service.key or other.service.kind is not ServiceKind.SEARCH:
                continue

            actions.append(
                ResultAction(
                    name=f"Open in {other.service.name}",
                    icon=_icon(other.service.icon),
                    context_data={"url": self._target_url(other, term)},
                    action=self._open_action,
                )
            )

        return actions

    def _summarize_action(self, url: str) -> List[ResultAction]:
        summarize = self.settings.config("summarize")
        if summarize is None or not summarize.enabled:
            return []

        return [
            ResultAction(
                name="Summarize this page",
                icon=_icon(summarize.service.icon),
                context_data={"url": build_url(summarize.service, url)},
                action=self._open_action,
            )
        ]

    def _refine_action(self, config: ServiceConfig, suggestion: str) -> ResultAction:
        prefix = f"{self.trigger_keyword} {config.keyword}".strip()
        return ResultAction(
            name="Put in search box",
            icon=_icon(config.service.icon),
            prevent_hide_after_action=True,
            context_data={"query": f"{prefix} {suggestion}"},
            action=self._change_query_action,
        )

    def _menu_actions(self, config: ServiceConfig, term: str) -> List[ResultAction]:
        if config.service.kind is ServiceKind.LAUNCH:
            return self._url_actions(build_url(config.service))

        prefix = f"{self.trigger_keyword} {config.keyword}".strip()
        return [
            ResultAction(
                name="Use this service",
                icon=_icon(config.service.icon),
                is_default=True,
                prevent_hide_after_action=True,
                context_data={"query": f"{prefix} {term}".rstrip() + " "},
                action=self._change_query_action,
            )
        ]

    async def _open_action(self, ctx: Context, action_context: ActionContext) -> None:
        url = (action_context.context_data or {}).get("url", "")
        if not url:
            return

        opened = await asyncio.to_thread(webbrowser.open, url)
        if not opened and self.api is not None:
            await self.api.notify(ctx, "Could not open a browser for this link")

    async def _copy_action(self, ctx: Context, action_context: ActionContext) -> None:
        text = (action_context.context_data or {}).get("text", "")
        if not text or self.api is None:
            return

        await self.api.copy(ctx, CopyParams(type=CopyType.TEXT, text=text))
        await self.api.notify(ctx, "Copied to clipboard")

    async def _change_query_action(self, ctx: Context, action_context: ActionContext) -> None:
        text = (action_context.context_data or {}).get("query", "")
        if not text or self.api is None:
            return

        await self.api.change_query(ctx, ChangeQueryParam(query_type=QueryType.INPUT, query_text=text))


def service_for(key: str) -> Service:
    """Look a service up by key. Kept public for tests and for scripts."""

    return SERVICES_BY_KEY[key]


plugin = KagiPlugin()

__all__ = ["KagiPlugin", "plugin", "service_for"]
