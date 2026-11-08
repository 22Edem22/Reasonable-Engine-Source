"""Curated AI providers, free tiers and image-generation options.

The catalogue is intentionally data-driven: the editor renders it, the agent uses
it, and users can override the endpoint/model of every provider in settings.
Provider availability and free limits change over time, so every network error is
surfaced to the user instead of silently falling back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from reasonable.core.i18n import current_language, tr


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    group: str
    kind: str
    base_url: str
    default_model: str
    requires_key: bool
    description: str
    key_url: str = ""
    docs_url: str = ""
    models_hint: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    supports_tools: bool = True
    note: str = ""
    # Optional override for the model-list endpoint. Most providers expose
    # ``{base_url}/models``; some gateways use a different path.
    models_url: str = ""
    # Conservative context window for the provider's default models. The
    # agent uses it to size its prompt-token budget; a user override can
    # raise or lower it per provider.
    context_window: int = 128_000

    @property
    def is_local(self) -> bool:
        return self.group == "Локальные"

    @property
    def display_name(self) -> str:
        if current_language() == "en":
            return _EN_PRESET_TEXT.get(self.id, {}).get("name") or self.name
        return self.name

    @property
    def display_group(self) -> str:
        if current_language() == "en":
            return _EN_PRESET_TEXT.get(self.id, {}).get("group") or self.group
        return self.group

    @property
    def display_description(self) -> str:
        if current_language() == "en":
            return _EN_PRESET_TEXT.get(self.id, {}).get("description") or self.description
        return self.description

    @property
    def display_note(self) -> str:
        if current_language() == "en":
            return _EN_PRESET_TEXT.get(self.id, {}).get("note") or self.note
        return self.note


PROVIDERS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="ollama",
        name="Ollama (локально)",
        group="Локальные",
        kind="openai",
        base_url="http://127.0.0.1:11434/v1",
        default_model="qwen2.5-coder:7b",
        requires_key=False,
        description=(
            "Полностью локальный сервер. Установите Ollama, скачайте модель и запустите "
            "`ollama serve`. Ключ не нужен, интернет не обязателен."
        ),
        docs_url="https://ollama.com/download",
        models_hint=("qwen2.5-coder:7b", "llama3.2", "deepseek-coder-v2", "mistral"),
        note="Для агентной работы рекомендуем модель от 7B параметров с поддержкой tool calling.",
        context_window=32_768,
    ),
    ProviderPreset(
        id="lmstudio",
        name="LM Studio (локально)",
        group="Локальные",
        kind="openai",
        base_url="http://127.0.0.1:1234/v1",
        default_model="local-model",
        requires_key=False,
        description=(
            "Локальный OpenAI-совместимый сервер LM Studio. Включите Local Server "
            "во вкладке Developer и загрузите модель."
        ),
        docs_url="https://lmstudio.ai",
        models_hint=("local-model",),
        note="Название модели можно получить кнопкой «Загрузить модели».",
        context_window=32_768,
    ),
    ProviderPreset(
        id="openrouter",
        name="OpenRouter (много бесплатных моделей)",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        default_model="meta-llama/llama-3.3-70b-instruct:free",
        requires_key=True,
        description=(
            "Один API-ключ — десятки моделей, включая бесплатные с суффиксом `:free`. "
            "Лучший выбор для полноценного встроенного агента."
        ),
        key_url="https://openrouter.ai/keys",
        docs_url="https://openrouter.ai/docs",
        models_hint=("meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3-0324:free", "qwen/qwen3-235b-a22b:free"),
        headers={"HTTP-Referer": "https://reasonable-engine.local", "X-Title": "Reasonable Engine"},
        note="После вставки ключа нажмите «Загрузить модели» и выберите модель с пометкой FREE.",
    ),
    ProviderPreset(
        id="groq",
        name="Groq Cloud",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        requires_key=True,
        description=(
            "Очень быстрый бесплатный тариф с щедрым лимитом запросов. Отлично подходит "
            "для итеративной работы ИИ-агента."
        ),
        key_url="https://console.groq.com/keys",
        docs_url="https://console.groq.com/docs",
        models_hint=("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"),
        note="Бесплатные лимиты указаны в консоли Groq и могут меняться.",
    ),
    ProviderPreset(
        id="gemini",
        name="Google AI Studio (Gemini)",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
        requires_key=True,
        description=(
            "Бесплатный тариф Gemini через OpenAI-совместимую точку входа. Хорошо "
            "справляется с кодом и длинным контекстом."
        ),
        key_url="https://aistudio.google.com/app/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs/openai",
        models_hint=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"),
        note="Используйте проект Google AI Studio, а не ключ Google Cloud, если хотите бесплатный тариф.",
        context_window=1_000_000,
    ),
    ProviderPreset(
        id="cerebras",
        name="Cerebras Inference",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://api.cerebras.ai/v1",
        default_model="llama-3.3-70b",
        requires_key=True,
        description=(
            "Бесплатный уровень с очень высокой скоростью генерации. Подходит для "
            "быстрых циклов «правка → проверка»."
        ),
        key_url="https://cloud.cerebras.ai/",
        docs_url="https://inference-docs.cerebras.ai",
        models_hint=("llama-3.3-70b", "qwen-3-32b"),
        note="Доступность и лимиты зависят от текущего free tier.",
    ),
    ProviderPreset(
        id="mistral",
        name="Mistral La Plateforme",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
        requires_key=True,
        description=(
            "Европейский провайдер с бесплатным экспериментальным уровнем. Хорошие "
            "модели для кода и текста."
        ),
        key_url="https://console.mistral.ai/api-keys",
        docs_url="https://docs.mistral.ai",
        models_hint=("mistral-small-latest", "codestral-latest"),
        note="Бесплатный experimental tier может требовать подтверждения телефона.",
    ),
    ProviderPreset(
        id="github",
        name="GitHub Models",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://models.github.ai/inference",
        default_model="openai/gpt-4o-mini",
        requires_key=True,
        description=(
            "Бесплатный доступ к моделям OpenAI, Meta, Mistral и другим через обычный "
            "GitHub PAT. Удобно, если у вас уже есть GitHub."
        ),
        key_url="https://github.com/settings/tokens",
        docs_url="https://docs.github.com/en/github-models",
        models_hint=("openai/gpt-4o-mini", "openai/gpt-4.1-mini", "meta/Llama-3.3-70B-Instruct"),
        note="Создайте fine-grained token с правом доступа к GitHub Models.",
    ),
    ProviderPreset(
        id="huggingface",
        name="Hugging Face Router",
        group="Бесплатный ключ",
        kind="openai",
        base_url="https://router.huggingface.co/v1",
        default_model="Qwen/Qwen2.5-72B-Instruct",
        requires_key=True,
        description=(
            "OpenAI-совместимый роутер к моделям Hugging Face. Есть небольшой бесплатный "
            "лимит кредитов и огромный каталог моделей."
        ),
        key_url="https://huggingface.co/settings/tokens",
        docs_url="https://huggingface.co/docs/inference-providers",
        models_hint=("Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"),
        note="Некоторые модели платные даже при наличии токена — проверяйте каталог.",
    ),
    ProviderPreset(
        id="openai",
        name="OpenAI API",
        group="Платные",
        kind="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4.1-mini",
        requires_key=True,
        description="Официальное API OpenAI. Стабильные tool calling и качество кода.",
        key_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs",
        models_hint=("gpt-4.1-mini", "gpt-4.1", "o4-mini"),
    ),
    ProviderPreset(
        id="anthropic",
        name="Anthropic Claude API",
        group="Платные",
        kind="anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-5",
        requires_key=True,
        description=(
            "Нативный API Claude с поддержкой инструментов. Один из лучших вариантов "
            "для автономной разработки проекта."
        ),
        key_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com",
        models_hint=("claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1"),
        context_window=200_000,
    ),
    ProviderPreset(
        id="opencode",
        name="OpenCode Go",
        group="Платные",
        kind="openai",
        base_url="https://opencode.ai/inference/go/openai/v1",
        default_model="deepseek-v4.1-flash",
        requires_key=True,
        description=(
            "Подписка OpenCode Go: один ключ Console даёт доступ к сильным кодовым "
            "моделям (DeepSeek, Kimi, GLM, Qwen, Claude Haiku и другим) с "
            "OpenAI-совместимым протоколом и поддержкой инструментов."
        ),
        key_url="https://opencode.ai/console",
        docs_url="https://opencode.ai/v2/docs/console/go/",
        models_hint=(
            "deepseek-v4.1-flash",
            "kimi-k2.7-code",
            "glm-5.3-flash",
            "qwen3.8-flash",
            "minimax-m3.1-flash",
        ),
        note=(
            "Вставьте личный ключ Console (oc_sk_…) или сервисного аккаунта. "
            "Reasonable Engine сам отправляет User-Agent и стабильный "
            "x-opencode-session, поэтому ошибка MissingSessionID не возникает."
        ),
        models_url="https://opencode.ai/inference/go/v1/models",
    ),
    ProviderPreset(
        id="custom",
        name="Свой OpenAI-совместимый сервер",
        group="Другое",
        kind="openai",
        base_url="",
        default_model="",
        requires_key=False,
        description=(
            "Любой сервер с эндпоинтом /chat/completions: vLLM, llama.cpp, LiteLLM, "
            "OpenWebUI, корпоративный шлюз и т. п."
        ),
        models_hint=(),
    ),
)

PROVIDER_MAP = {provider.id: provider for provider in PROVIDERS}
PROVIDER_GROUPS = (
    "Локальные",
    "Бесплатный ключ",
    "Платные",
    "Другое",
)

# English display text for the provider catalogue. Canonical (Russian) values
# stay on the dataclasses so tests and internal comparisons keep working; the
# editor renders the ``display_*`` properties.
_EN_PRESET_TEXT: dict[str, dict[str, str]] = {
    "ollama": {
        "name": "Ollama (local)",
        "group": "Local",
        "description": (
            "Fully local server. Install Ollama, pull a model and run `ollama serve`. "
            "No key needed, no internet required."
        ),
        "note": "For agent work we recommend a 7B+ model with tool calling support.",
    },
    "lmstudio": {
        "name": "LM Studio (local)",
        "group": "Local",
        "description": (
            "Local OpenAI-compatible LM Studio server. Enable Local Server on the "
            "Developer tab and load a model."
        ),
        "note": "You can get the model name with the “Load models” button.",
    },
    "openrouter": {
        "name": "OpenRouter (many free models)",
        "group": "Free key",
        "description": (
            "One API key — dozens of models, including free ones with the `:free` suffix. "
            "The best choice for a full built-in agent."
        ),
        "note": "After pasting the key press “Load models” and pick a model marked FREE.",
    },
    "groq": {
        "name": "Groq Cloud",
        "group": "Free key",
        "description": (
            "Very fast free tier with a generous request limit. A great fit for "
            "iterative AI-agent work."
        ),
        "note": "Free limits are listed in the Groq console and may change.",
    },
    "gemini": {
        "name": "Google AI Studio (Gemini)",
        "group": "Free key",
        "description": (
            "Free Gemini tier through the OpenAI-compatible endpoint. Handles code "
            "and long context well."
        ),
        "note": "Use a Google AI Studio project, not a Google Cloud key, if you want the free tier.",
    },
    "cerebras": {
        "name": "Cerebras Inference",
        "group": "Free key",
        "description": (
            "Free tier with very high generation speed. Fits fast “edit → check” loops."
        ),
        "note": "Availability and limits depend on the current free tier.",
    },
    "mistral": {
        "name": "Mistral La Plateforme",
        "group": "Free key",
        "description": (
            "European provider with a free experimental tier. Good models for code and text."
        ),
        "note": "The free experimental tier may require phone verification.",
    },
    "github": {
        "name": "GitHub Models",
        "group": "Free key",
        "description": (
            "Free access to OpenAI, Meta, Mistral and other models via a regular GitHub PAT. "
            "Handy if you already use GitHub."
        ),
        "note": "Create a fine-grained token with access to GitHub Models.",
    },
    "huggingface": {
        "name": "Hugging Face Router",
        "group": "Free key",
        "description": (
            "OpenAI-compatible router to Hugging Face models. A small free credit limit "
            "and a huge model catalog."
        ),
        "note": "Some models are paid even with a token — check the catalog.",
    },
    "openai": {
        "name": "OpenAI API",
        "group": "Paid",
        "description": "Official OpenAI API. Stable tool calling and code quality.",
    },
    "anthropic": {
        "name": "Anthropic Claude API",
        "group": "Paid",
        "description": (
            "Native Claude API with tool support. One of the best options for "
            "autonomous project development."
        ),
    },
    "opencode": {
        "name": "OpenCode Go",
        "group": "Paid",
        "description": (
            "An OpenCode Go subscription: one Console key unlocks strong coding "
            "models (DeepSeek, Kimi, GLM, Qwen, Claude Haiku and more) through an "
            "OpenAI-compatible protocol with tool support."
        ),
        "note": (
            "Paste a personal Console key (oc_sk_…) or a service-account key. "
            "Reasonable Engine sends its own User-Agent and a stable "
            "x-opencode-session, so the MissingSessionID error does not occur."
        ),
    },
    "custom": {
        "name": "Custom OpenAI-compatible server",
        "group": "Other",
        "description": (
            "Any server with a /chat/completions endpoint: vLLM, llama.cpp, LiteLLM, "
            "OpenWebUI, a corporate gateway, etc."
        ),
    },
}


_GROUP_LABELS = {
    "Локальные": ("Local", "Локальные"),
    "Бесплатный ключ": ("Free key", "Бесплатный ключ"),
    "Платные": ("Paid", "Платные"),
    "Другое": ("Other", "Другое"),
}


def provider_group_label(group: str) -> str:
    """Localized section title for a canonical group name."""
    en, ru = _GROUP_LABELS.get(group, (group, group))
    return tr(en, ru)


@dataclass(frozen=True)
class ImageProviderPreset:
    id: str
    name: str
    description: str
    base_url: str
    default_model: str
    requires_key: bool = False
    key_url: str = ""

    @property
    def display_name(self) -> str:
        if current_language() == "en":
            return _EN_IMAGE_TEXT.get(self.id, {}).get("name") or self.name
        return self.name

    @property
    def display_description(self) -> str:
        if current_language() == "en":
            return _EN_IMAGE_TEXT.get(self.id, {}).get("description") or self.description
        return self.description


_EN_IMAGE_TEXT: dict[str, dict[str, str]] = {
    "openai": {
        "name": "OpenAI-compatible images",
        "description": (
            "A local or remote server with a /images/generations endpoint "
            "(OpenAI, ComfyUI proxy, SD WebUI proxy, etc.)."
        ),
    },
}


IMAGE_PROVIDERS: tuple[ImageProviderPreset, ...] = (
    ImageProviderPreset(
        id="openai",
        name="OpenAI-совместимые изображения",
        description=(
            "Локальный или удалённый сервер с эндпоинтом /images/generations "
            "(OpenAI, ComfyUI-прокси, SD WebUI-прокси и т. п.)."
        ),
        base_url="https://api.openai.com/v1",
        default_model="gpt-image-1",
        requires_key=True,
        key_url="https://platform.openai.com/api-keys",
    ),
)

IMAGE_PROVIDER_MAP = {provider.id: provider for provider in IMAGE_PROVIDERS}


@dataclass(frozen=True)
class FreeApiSite:
    name: str
    url: str
    models: str
    note: str
    badge: str = "FREE TIER"

    @property
    def display_models(self) -> str:
        if current_language() == "en":
            return _EN_SITE_TEXT.get(self.name, {}).get("models") or self.models
        return self.models

    @property
    def display_note(self) -> str:
        if current_language() == "en":
            return _EN_SITE_TEXT.get(self.name, {}).get("note") or self.note
        return self.note

    @property
    def display_badge(self) -> str:
        if current_language() == "en":
            return _EN_SITE_TEXT.get(self.name, {}).get("badge") or self.badge
        return self.badge


_EN_SITE_TEXT: dict[str, dict[str, str]] = {
    "OpenRouter": {
        "models": "Llama, Qwen, DeepSeek, Mistral and dozens more",
        "note": "Models with the :free suffix. One key for everything. Free request limits depend on the account.",
        "badge": "RECOMMENDED",
    },
    "Google AI Studio": {
        "models": "Gemini 2.5 Flash / Pro",
        "note": "Free tier with per-minute and daily request limits. The key is created in one click.",
    },
    "Groq Cloud": {
        "models": "Llama 3.3 70B, Qwen 3",
        "note": "Very fast generation, a free tier and a clear limits console.",
    },
    "Cerebras": {
        "models": "Llama, Qwen",
        "note": "Free tier for developers, high token speed.",
    },
    "GitHub Models": {
        "models": "GPT-4o mini, Llama, Mistral",
        "note": "Free with limits for GitHub users. Needs a fine-grained token.",
    },
    "Mistral": {
        "models": "Mistral Small, Codestral",
        "note": "Free experimental tier. Phone verification may be required.",
    },
    "Hugging Face": {
        "models": "A huge catalog of open-source models",
        "note": "A small free credit limit; some models are paid.",
    },
    "Cloudflare Workers AI": {
        "models": "Llama, Qwen, Mistral",
        "note": "A daily free neuron quota. Needs a Cloudflare account.",
    },
}


FREE_API_SITES: tuple[FreeApiSite, ...] = (
    FreeApiSite(
        "OpenRouter",
        "https://openrouter.ai/models?max_price=0",
        "Llama, Qwen, DeepSeek, Mistral и десятки других",
        "Модели с суффиксом :free. Один ключ на всё. Лимиты на бесплатные запросы зависят от аккаунта.",
        "РЕКОМЕНДУЕМ",
    ),
    FreeApiSite(
        "Google AI Studio",
        "https://aistudio.google.com/app/apikey",
        "Gemini 2.5 Flash / Pro",
        "Бесплатный тариф с ограничением запросов в минуту и день. Ключ создаётся в один клик.",
    ),
    FreeApiSite(
        "Groq Cloud",
        "https://console.groq.com/keys",
        "Llama 3.3 70B, Qwen 3",
        "Очень быстрая генерация, бесплатный уровень и понятная консоль лимитов.",
    ),
    FreeApiSite(
        "Cerebras",
        "https://cloud.cerebras.ai/",
        "Llama, Qwen",
        "Бесплатный уровень для разработчиков, высокая скорость токенов.",
    ),
    FreeApiSite(
        "GitHub Models",
        "https://github.com/settings/tokens",
        "GPT-4o mini, Llama, Mistral",
        "Бесплатно с лимитами для пользователей GitHub. Нужен fine-grained token.",
    ),
    FreeApiSite(
        "Mistral",
        "https://console.mistral.ai/api-keys",
        "Mistral Small, Codestral",
        "Бесплатный experimental tier. Может потребоваться верификация телефона.",
    ),
    FreeApiSite(
        "Hugging Face",
        "https://huggingface.co/settings/tokens",
        "Огромный каталог open-source моделей",
        "Небольшой бесплатный лимит кредитов; часть моделей платная.",
    ),
    FreeApiSite(
        "Cloudflare Workers AI",
        "https://dash.cloudflare.com/profile/api-tokens",
        "Llama, Qwen, Mistral",
        "Ежедневная бесплатная квота нейронов. Нужен аккаунт Cloudflare.",
    ),
)


def get_provider(provider_id: str) -> ProviderPreset:
    return PROVIDER_MAP.get(provider_id, PROVIDER_MAP["custom"])


def providers_in_group(group: str) -> Iterable[ProviderPreset]:
    return (provider for provider in PROVIDERS if provider.group == group)


def get_image_provider(provider_id: str) -> ImageProviderPreset:
    return IMAGE_PROVIDER_MAP.get(provider_id, IMAGE_PROVIDER_MAP["openai"])


def merge_provider_config(settings, provider_id: str) -> dict:
    """Return effective provider settings (preset + user override)."""
    preset = get_provider(provider_id)
    override = settings.data.get("provider_overrides", {}).get(provider_id, {}) if settings else {}
    try:
        context_window = max(
            4_000, int(override.get("context_window") or preset.context_window or 128_000)
        )
    except (TypeError, ValueError):
        context_window = 128_000
    return {
        "id": preset.id,
        "name": preset.display_name,
        "kind": override.get("kind", preset.kind),
        "base_url": (override.get("base_url") or preset.base_url).strip(),
        "models_url": str(override.get("models_url") or preset.models_url).strip(),
        "context_window": context_window,
        "model": (override.get("model") or preset.default_model).strip(),
        "api_key": (override.get("api_key") or "").strip(),
        "requires_key": preset.requires_key,
        "headers": {**preset.headers, **(override.get("headers") or {})},
        "group": preset.group,
        "group_label": preset.display_group,
        "description": preset.display_description,
        "key_url": preset.key_url,
        "docs_url": preset.docs_url,
        "note": preset.display_note,
    }


def short_provider_name(name: object, fallback: str = "") -> str:
    """Return a compact provider name for chrome and chat headers.

    Catalog labels may include an access hint in parentheses, for example
    ``OpenRouter (много бесплатных моделей)``. Settings still show the full
    label; headers use the part before the hint and keep the full value in a
    tooltip.
    """
    text = str(name or fallback or tr("AI", "ИИ"))
    short = text.split("(", 1)[0].strip()
    return short or text


def config_status(config: dict) -> tuple[bool, str]:
    if not config.get("base_url"):
        return False, tr("Set the Base URL", "Укажите Base URL")
    if not config.get("model"):
        return False, tr("Set the model", "Укажите модель")
    if config.get("requires_key") and not config.get("api_key"):
        return False, tr("An API key is required", "Нужен API-ключ")
    return True, tr("Ready", "Готово")
