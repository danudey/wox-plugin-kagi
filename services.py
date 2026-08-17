"""Catalog of the Kagi services this plugin can drive.

Every service is described declaratively so that settings, command registration
and URL building all read from the same source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Optional
from urllib.parse import urlencode


class ServiceKind(str, Enum):
    """How a service consumes the text the user typed."""

    SEARCH = "search"
    """Takes a search term and opens a Kagi results page."""

    TEXT = "text"
    """Takes free-form text (translate, proofread, dictionary)."""

    URL = "url"
    """Takes a URL or a document reference (summarizer)."""

    LAUNCH = "launch"
    """Takes no argument, the plugin just opens the product."""


@dataclass(frozen=True)
class Service:
    """A single Kagi product or search vertical."""

    key: str
    """Stable identifier, used to build setting keys such as `service_news_enabled`."""

    name: str
    """Human readable name shown in results and in the settings panel."""

    description: str
    """One line explanation shown as the result subtitle and setting tooltip."""

    default_keyword: str
    """Keyword the user types after the trigger keyword. Empty means "no keyword"."""

    icon: str
    """Path of the icon, relative to the plugin root."""

    kind: ServiceKind

    base_url: str
    """Web URL opened in the browser."""

    param: str = "q"
    """Name of the query string parameter carrying the user's text."""

    placeholder: str = "query"
    """Word used in prompts such as "Type a query"."""

    search_label: str = ""
    """Name used inside a sentence, as in "Search Kagi Images for …". Defaults to `name`."""

    supports_suggestions: bool = False
    """Whether Kagi autocomplete suggestions make sense for this service."""

    api_capability: str = ""
    """Which Kagi API can answer inline: "search", "news", "fastgpt" or "summarize"."""

    extra_params: Mapping[str, str] = field(default_factory=dict)
    """Static query string parameters always appended to `base_url`."""


WEB = Service(
    key="web",
    name="Web Search",
    description="Search the web with Kagi",
    default_keyword="",
    icon="icons/search.svg",
    kind=ServiceKind.SEARCH,
    base_url="https://kagi.com/search",
    search_label="Kagi",
    supports_suggestions=True,
    api_capability="search",
)

SERVICES: List[Service] = [
    WEB,
    Service(
        key="images",
        name="Image Search",
        description="Search Kagi Images",
        default_keyword="img",
        icon="icons/images.svg",
        kind=ServiceKind.SEARCH,
        base_url="https://kagi.com/images",
        search_label="Kagi Images",
        supports_suggestions=True,
    ),
    Service(
        key="videos",
        name="Video Search",
        description="Search Kagi Videos",
        default_keyword="vid",
        icon="icons/videos.svg",
        kind=ServiceKind.SEARCH,
        base_url="https://kagi.com/videos",
        search_label="Kagi Videos",
        supports_suggestions=True,
    ),
    Service(
        key="news",
        name="News Search",
        description="Search Kagi News results",
        default_keyword="news",
        icon="icons/news.svg",
        kind=ServiceKind.SEARCH,
        base_url="https://kagi.com/news",
        search_label="Kagi News",
        supports_suggestions=True,
        api_capability="news",
    ),
    Service(
        key="podcasts",
        name="Podcast Search",
        description="Search Kagi Podcasts",
        default_keyword="pod",
        icon="icons/podcasts.svg",
        kind=ServiceKind.SEARCH,
        base_url="https://kagi.com/podcasts",
        search_label="Kagi Podcasts",
        supports_suggestions=True,
    ),
    Service(
        key="maps",
        name="Maps",
        description="Find a place on Kagi Maps",
        default_keyword="map",
        icon="icons/maps.svg",
        kind=ServiceKind.SEARCH,
        base_url="https://kagi.com/maps/",
        search_label="Kagi Maps",
        placeholder="place",
        supports_suggestions=True,
    ),
    Service(
        key="assistant",
        name="Assistant",
        description="Ask the Kagi Assistant",
        default_keyword="ask",
        icon="icons/assistant.svg",
        kind=ServiceKind.TEXT,
        base_url="https://assistant.kagi.com/",
        placeholder="question",
    ),
    Service(
        key="fastgpt",
        name="Quick Answer",
        description="Ask FastGPT for a cited answer",
        default_keyword="gpt",
        icon="icons/fastgpt.svg",
        kind=ServiceKind.TEXT,
        base_url="https://kagi.com/fastgpt",
        param="query",
        placeholder="question",
        api_capability="fastgpt",
    ),
    Service(
        key="summarize",
        name="Universal Summarizer",
        description="Summarize a page, video or document",
        default_keyword="sum",
        icon="icons/universal_summarizer.svg",
        kind=ServiceKind.URL,
        base_url="https://kagi.com/summarizer",
        param="url",
        placeholder="URL",
        api_capability="summarize",
    ),
    Service(
        key="translate",
        name="Translate",
        description="Translate text or a web page with Kagi Translate",
        default_keyword="tr",
        icon="icons/translate.svg",
        kind=ServiceKind.TEXT,
        base_url="https://translate.kagi.com/",
        param="text",
        placeholder="text",
    ),
    Service(
        key="proofread",
        name="Proofread",
        description="Correct grammar and style with Kagi Translate",
        default_keyword="proof",
        icon="icons/proofread.svg",
        kind=ServiceKind.TEXT,
        base_url="https://translate.kagi.com/proofread",
        param="text",
        placeholder="text",
    ),
    Service(
        key="dictionary",
        name="Dictionary",
        description="Look a word up in the Kagi dictionary",
        default_keyword="dict",
        icon="icons/dictionary.svg",
        kind=ServiceKind.TEXT,
        base_url="https://translate.kagi.com/dictionary",
        param="word",
        placeholder="word",
    ),
    Service(
        key="smallweb",
        name="Small Web",
        description="Discover independent, non commercial websites",
        default_keyword="small",
        icon="icons/small_web.svg",
        kind=ServiceKind.LAUNCH,
        base_url="https://kagi.com/smallweb/",
        api_capability="smallweb",
    ),
    Service(
        key="kagi_news",
        name="Kagi News",
        description="Open the Kagi News (Kite) daily briefing",
        default_keyword="kite",
        icon="icons/kagi_news.svg",
        kind=ServiceKind.LAUNCH,
        base_url="https://news.kagi.com/",
    ),
]

SERVICES_BY_KEY: Dict[str, Service] = {service.key: service for service in SERVICES}


def build_url(service: Service, term: str = "", extra: Optional[Mapping[str, str]] = None) -> str:
    """Build the browser URL for `service`, carrying `term` and any extra parameters."""

    params: Dict[str, str] = dict(service.extra_params)
    if extra:
        params.update({key: value for key, value in extra.items() if value})

    term = term.strip()
    if term and service.kind is not ServiceKind.LAUNCH:
        params[service.param] = term

    if not params:
        return service.base_url

    separator = "&" if "?" in service.base_url else "?"
    return f"{service.base_url}{separator}{urlencode(params)}"
