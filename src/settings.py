"""Reading and validating the plugin settings defined in `plugin.json`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from .services import SERVICES, Service

SettingReader = Callable[[str], Awaitable[str]]

API_KEY = "api_key"
REQUEST_TIMEOUT = "request_timeout"
SUGGESTIONS_ENABLED = "suggestions_enabled"
SUGGESTIONS_LIMIT = "suggestions_limit"
API_SEARCH_INLINE = "api_search_inline"
API_FASTGPT_INLINE = "api_fastgpt_inline"
API_SUMMARIZER_INLINE = "api_summarizer_inline"
API_RESULT_LIMIT = "api_result_limit"
TRANSLATE_SOURCE = "translate_source"
TRANSLATE_TARGET = "translate_target"
SUMMARIZER_ENGINE = "summarizer_engine"
SUMMARIZER_TYPE = "summarizer_type"
SUMMARIZER_LANGUAGE = "summarizer_language"

DEFAULTS: Dict[str, str] = {
    API_KEY: "",
    REQUEST_TIMEOUT: "6",
    SUGGESTIONS_ENABLED: "true",
    SUGGESTIONS_LIMIT: "6",
    API_SEARCH_INLINE: "false",
    API_FASTGPT_INLINE: "false",
    API_SUMMARIZER_INLINE: "false",
    API_RESULT_LIMIT: "5",
    TRANSLATE_SOURCE: "auto",
    TRANSLATE_TARGET: "en",
    SUMMARIZER_ENGINE: "cecil",
    SUMMARIZER_TYPE: "summary",
    SUMMARIZER_LANGUAGE: "",
}


def enabled_key(service: Service) -> str:
    return f"service_{service.key}_enabled"


def keyword_key(service: Service) -> str:
    return f"service_{service.key}_keyword"


@dataclass
class ServiceConfig:
    """A service plus the user's choices for it."""

    service: Service
    enabled: bool
    keyword: str


@dataclass
class PluginSettings:
    """Everything the plugin needs to answer a query."""

    api_key: str = ""
    request_timeout: float = 6.0
    suggestions_enabled: bool = True
    suggestions_limit: int = 6
    api_search_inline: bool = False
    api_fastgpt_inline: bool = False
    api_summarizer_inline: bool = False
    api_result_limit: int = 5
    translate_source: str = "auto"
    translate_target: str = "en"
    summarizer_engine: str = "cecil"
    summarizer_type: str = "summary"
    summarizer_language: str = ""
    services: Dict[str, ServiceConfig] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def config(self, key: str) -> Optional[ServiceConfig]:
        return self.services.get(key)

    def is_enabled(self, key: str) -> bool:
        config = self.services.get(key)
        return bool(config and config.enabled)

    def enabled_services(self) -> List[ServiceConfig]:
        """Enabled services, in catalog order."""

        return [self.services[service.key] for service in SERVICES if self.is_enabled(service.key)]

    def match_keyword(self, token: str) -> Optional[ServiceConfig]:
        """Find the enabled service owning `token`, comparing case insensitively."""

        token = token.strip().lower()
        if not token:
            return None

        for config in self.enabled_services():
            if config.keyword and config.keyword.lower() == token:
                return config

        return None

    def translate_params(self) -> Dict[str, str]:
        return {"from": self.translate_source, "to": self.translate_target}


def _as_bool(value: str, fallback: bool) -> bool:
    value = (value or "").strip().lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    return fallback


def _as_int(value: str, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float((value or "").strip()))
    except ValueError:
        return fallback
    return max(minimum, min(maximum, parsed))


def _as_float(value: str, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float((value or "").strip())
    except ValueError:
        return fallback
    return max(minimum, min(maximum, parsed))


def _normalise_keyword(value: str) -> str:
    """Keywords are single tokens, so only the first word is kept."""

    return (value or "").strip().split(" ")[0].strip().lower()


def build_settings(values: Dict[str, str]) -> PluginSettings:
    """Turn raw setting strings into a validated `PluginSettings`.

    Kept free of any Wox API call so it can be unit tested directly.
    """

    def raw(key: str) -> str:
        value = values.get(key)
        return DEFAULTS.get(key, "") if value is None or value == "" else value

    settings = PluginSettings(
        api_key=raw(API_KEY).strip(),
        request_timeout=_as_float(raw(REQUEST_TIMEOUT), 6.0, 1.0, 60.0),
        suggestions_enabled=_as_bool(raw(SUGGESTIONS_ENABLED), True),
        suggestions_limit=_as_int(raw(SUGGESTIONS_LIMIT), 6, 0, 15),
        api_search_inline=_as_bool(raw(API_SEARCH_INLINE), False),
        api_fastgpt_inline=_as_bool(raw(API_FASTGPT_INLINE), False),
        api_summarizer_inline=_as_bool(raw(API_SUMMARIZER_INLINE), False),
        api_result_limit=_as_int(raw(API_RESULT_LIMIT), 5, 1, 20),
        translate_source=raw(TRANSLATE_SOURCE).strip() or "auto",
        translate_target=raw(TRANSLATE_TARGET).strip() or "en",
        summarizer_engine=raw(SUMMARIZER_ENGINE).strip() or "cecil",
        summarizer_type=raw(SUMMARIZER_TYPE).strip() or "summary",
        summarizer_language=raw(SUMMARIZER_LANGUAGE).strip(),
    )

    claimed: Dict[str, str] = {}
    for service in SERVICES:
        enabled_value = values.get(enabled_key(service))
        enabled = _as_bool(enabled_value, True) if enabled_value else True

        keyword_value = values.get(keyword_key(service))
        keyword = _normalise_keyword(service.default_keyword if keyword_value is None else keyword_value)

        if keyword and keyword in claimed:
            settings.warnings.append(
                f'Keyword "{keyword}" is used by both {claimed[keyword]} and {service.name}, so {service.name} has no keyword.'
            )
            keyword = ""
        elif keyword:
            claimed[keyword] = service.name

        settings.services[service.key] = ServiceConfig(service=service, enabled=enabled, keyword=keyword)

    if not settings.enabled_services():
        settings.warnings.append("Every Kagi service is disabled. Enable at least one in the plugin settings.")

    return settings


def setting_keys() -> List[str]:
    """All setting keys the plugin reads, including the per service ones."""

    keys = list(DEFAULTS)
    for service in SERVICES:
        keys.append(enabled_key(service))
        keys.append(keyword_key(service))
    return keys


async def load_settings(read: SettingReader) -> PluginSettings:
    """Read every setting through `read` and validate the result."""

    values: Dict[str, str] = {}
    for key in setting_keys():
        try:
            values[key] = await read(key)
        except Exception:
            values[key] = ""

    return build_settings(values)


def split_command(text: str) -> Tuple[str, str]:
    """Split "img cats" into ("img", "cats")."""

    stripped = text.strip()
    if not stripped:
        return "", ""

    head, _, tail = stripped.partition(" ")
    return head, tail.strip()
