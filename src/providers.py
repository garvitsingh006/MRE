"""OpenAI-compatible Gemini/Groq client with rate-limit fallback."""
import os
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from filelock import FileLock
from openai import APIStatusError, OpenAI, RateLimitError

from src.config import LLM_USAGE_PATH


_MAX_COMPLETION_TOKENS = 1000

_PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "openai/gpt-oss-120b",
    },
}


@dataclass
class ProviderResponse:
    content: str
    provider: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cached: bool = False

    @property
    def total_tokens(self) -> Optional[int]:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _provider_order() -> List[str]:
    preferred = os.getenv("PROVIDER", "gemini").strip().lower()
    if preferred not in _PROVIDERS:
        raise ValueError(
            "PROVIDER must be 'gemini' or 'groq'; received {!r}.".format(preferred)
        )
    return [preferred] + [name for name in _PROVIDERS if name != preferred]


def _api_key(provider: str) -> str:
    return os.getenv(_PROVIDERS[provider]["key_env"], "").strip()


def _model(provider: str, preferred: str) -> str:
    provider_model = os.getenv(_PROVIDERS[provider]["model_env"], "").strip()
    generic_model = os.getenv("MODEL", "").strip()
    if provider_model:
        return provider_model
    if provider == preferred and generic_model:
        return generic_model
    return str(_PROVIDERS[provider]["default_model"])


def _request(provider: str, model: str, api_key: str, messages: List[Dict[str, str]]) -> ProviderResponse:
    client = OpenAI(
        api_key=api_key,
        base_url=str(_PROVIDERS[provider]["base_url"]),
        timeout=60,
        max_retries=0,
    )
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.1,
        max_tokens=_MAX_COMPLETION_TOKENS,
    )
    if not completion.choices or completion.choices[0].message.content is None:
        raise RuntimeError("{} returned an empty chat response.".format(provider))
    usage = completion.usage
    return ProviderResponse(
        content=completion.choices[0].message.content,
        provider=provider,
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
    )


def _read_daily_usage(usage_path) -> Dict[str, Any]:
    if not usage_path.is_file():
        return {"date": datetime.now(timezone.utc).date().isoformat(), "providers": {}}
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    if not isinstance(usage, dict) or not isinstance(usage.get("providers"), dict):
        raise ValueError("LLM usage ledger has an invalid JSON structure.")
    if usage.get("date") != datetime.now(timezone.utc).date().isoformat():
        return {"date": datetime.now(timezone.utc).date().isoformat(), "providers": {}}
    return usage


def _check_daily_budget(
    provider: str, messages: List[Dict[str, str]], usage: Dict[str, Any]
) -> None:
    limit_name = "{}_DAILY_TOKEN_LIMIT".format(provider.upper())
    raw_limit = os.getenv(limit_name, "").strip()
    if not raw_limit:
        return
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("{} must be a positive integer.".format(limit_name)) from exc
    if limit < 1:
        raise ValueError("{} must be a positive integer.".format(limit_name))
    provider_usage = usage["providers"].get(provider, {})
    used = int(provider_usage.get("tokens", 0))
    prompt_reserve = len(
        json.dumps(messages, ensure_ascii=False).encode("utf-8")
    )
    if used + prompt_reserve + _MAX_COMPLETION_TOKENS > limit:
        raise RuntimeError(
            "{} is at its configured daily token limit ({} of {} tokens used)."
            .format(provider, used, limit)
        )


def chat(messages: List[Dict[str, str]]) -> ProviderResponse:
    """Send a chat request; try the other configured provider only after HTTP 429."""
    load_dotenv()
    order = _provider_order()
    configured = [provider for provider in order if _api_key(provider)]
    if not configured:
        missing = ", ".join(_PROVIDERS[provider]["key_env"] for provider in order)
        raise RuntimeError(
            "No LLM API key is configured. Set at least one of: {}.".format(missing)
        )
    preferred = order[0]
    rate_limit_error: Optional[BaseException] = None
    LLM_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    for provider in configured:
        with FileLock(str(LLM_USAGE_PATH.with_suffix(".lock"))):
            usage = _read_daily_usage(LLM_USAGE_PATH)
            _check_daily_budget(provider, messages, usage)
            try:
                response = _request(
                    provider,
                    _model(provider, preferred),
                    _api_key(provider),
                    messages,
                )
            except RateLimitError as exc:
                rate_limit_error = exc
                continue
            except APIStatusError as exc:
                if exc.status_code != 429:
                    raise RuntimeError(
                        "{} API request failed with HTTP {}.".format(
                            provider, exc.status_code
                        )
                    ) from exc
                rate_limit_error = exc
            else:
                provider_usage = usage["providers"].setdefault(
                    provider, {"tokens": 0, "calls": 0, "unknown_token_calls": 0}
                )
                provider_usage["calls"] += 1
                if response.total_tokens is None:
                    provider_usage["unknown_token_calls"] += 1
                else:
                    provider_usage["tokens"] += response.total_tokens
                LLM_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
                temporary_path = LLM_USAGE_PATH.with_suffix(".tmp")
                temporary_path.write_text(
                    json.dumps(usage, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                temporary_path.replace(LLM_USAGE_PATH)
                return response
    if rate_limit_error is not None:
        raise RuntimeError(
            "All configured LLM providers are rate-limited. Try again later."
        ) from rate_limit_error
    raise RuntimeError("No LLM provider was available.")