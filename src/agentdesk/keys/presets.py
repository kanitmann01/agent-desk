"""The preset catalog: verified base URLs and the consoles that hand out keys.

Every base URL comes from the provider research pass (docs/research/byok/
04-multi-key-models.md section 6) and the console URL is the page that
issues a key, so the two first-run stumbles (where do I get a key, what
is the base URL) are answered by facts rather than documentation reading.
Local presets mark the key optional: they need no secret and no keychain.
"""

from dataclasses import dataclass

__all__ = ["Preset", "PRESETS", "preset_for"]


@dataclass(frozen=True)
class Preset:
    """One provider: its default base URL, its key console, whether a
    key is optional (the local servers) and whether it is local."""

    id: str
    name: str
    base_url: str
    console_url: str
    key_optional: bool = False

    @property
    def local(self) -> bool:
        """Local presets run on this machine and never need a key."""
        return self.key_optional


PRESETS: tuple[Preset, ...] = (
    Preset("openai", "OpenAI",
           "https://api.openai.com/v1",
           "https://platform.openai.com/api-keys"),
    Preset("anthropic-compat", "Anthropic (compatibility)",
           "https://api.anthropic.com/v1/",
           "https://console.anthropic.com/settings/keys"),
    Preset("openrouter", "OpenRouter",
           "https://openrouter.ai/api/v1",
           "https://openrouter.ai/settings/keys"),
    Preset("groq", "Groq",
           "https://api.groq.com/openai/v1",
           "https://console.groq.com/keys"),
    Preset("together", "Together",
           "https://api.together.ai/v1",
           "https://api.together.ai/settings/api-keys"),
    Preset("gemini", "Google Gemini",
           "https://generativelanguage.googleapis.com/v1beta/openai/",
           "https://aistudio.google.com/app/apikey"),
    Preset("deepseek", "DeepSeek",
           "https://api.deepseek.com/v1",
           "https://platform.deepseek.com/api_keys"),
    Preset("mistral", "Mistral",
           "https://api.mistral.ai/v1",
           "https://console.mistral.ai/api-keys"),
    Preset("opencode", "OpenCode Go",
           "https://opencode.ai/inference/go/v1",
           "https://opencode.ai/v2/docs/console/go/"),
    Preset("ollama", "Ollama",
           "http://localhost:11434/v1", "", key_optional=True),
    Preset("lmstudio", "LM Studio",
           "http://localhost:1234/v1", "", key_optional=True),
    Preset("vllm", "vLLM",
           "http://localhost:8000/v1", "", key_optional=True),
    Preset("custom", "Custom",
           "", ""),
)


def preset_for(provider_id: str) -> Preset | None:
    """The preset with this id, or None when no preset carries it."""
    for preset in PRESETS:
        if preset.id == provider_id:
            return preset
    return None
