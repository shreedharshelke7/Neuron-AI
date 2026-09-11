"""Application configuration and secret-safe settings management for Neuron AI.

Loads configuration from environment variables and local .env files.
Guarantees:
- API credentials are never exposed in string representations or logs.
- Safe defaults for offline and demo execution.
- Single source of truth for runtime configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.utils.paths import get_app_root


def _mask_secret(val: Optional[str]) -> str:
    """Mask a secret key for safe representation."""
    if not val:
        return "<unset>"
    clean = val.strip()
    if len(clean) <= 8:
        return "****"
    return f"{clean[:3]}...{clean[-4:]}"


def _load_env_file(env_path: str) -> Dict[str, str]:
    """Parse key-value pairs from an env file safely."""
    pairs: Dict[str, str] = {}
    if not os.path.exists(env_path):
        return pairs

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    pairs[key] = val
    except Exception:
        pass
    return pairs


@dataclass
class NeuronSettings:
    """Neuron AI application runtime settings."""

    llm_provider: str = "gemini"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"

    stt_provider: str = "whisper"
    whisper_model: str = "base.en"

    tts_provider: str = "elevenlabs"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_model_id: str = "eleven_turbo_v2_5"

    wake_word_enabled: bool = True
    wake_word_phrase: str = "Hey Neuron"

    demo_mode: str = "auto"
    demo_scenario: Optional[str] = None

    metrics_enabled: bool = True
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Normalize key aliases."""
        if hasattr(self, "_google_api_key") and self._google_api_key and not self.gemini_api_key:
            self.gemini_api_key = self._google_api_key

    @property
    def google_api_key(self) -> Optional[str]:
        return self.gemini_api_key

    @google_api_key.setter
    def google_api_key(self, val: Optional[str]) -> None:
        self.gemini_api_key = val

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> NeuronSettings:
        """Create a NeuronSettings instance resolved from environment and .env file."""
        if env_file is None:
            env_file = os.path.join(get_app_root(), ".env")

        env_file_data = _load_env_file(env_file)

        def get_val(key: str, default: Any) -> Any:
            # os.environ takes precedence over .env file
            if key in os.environ and os.environ[key].strip():
                return os.environ[key].strip()
            if key in env_file_data and env_file_data[key].strip():
                return env_file_data[key].strip()
            return default

        gemini_key = get_val("GEMINI_API_KEY", None) or get_val("GOOGLE_API_KEY", None)
        if not gemini_key:
            try:
                from app.config.credentials import get_gemini_api_key
                gemini_key = get_gemini_api_key()
            except Exception:
                pass

        eleven_key = get_val("ELEVENLABS_API_KEY", None)
        if not eleven_key:
            try:
                from app.config.credentials import get_elevenlabs_api_key
                eleven_key = get_elevenlabs_api_key()
            except Exception:
                pass

        voice_id = get_val("ELEVENLABS_VOICE_ID", None)
        if not voice_id:
            try:
                from app.config.user_config import get_user_voice_id
                voice_id = get_user_voice_id()
            except Exception:
                pass

        wake_enabled_str = str(get_val("NEURON_WAKE_WORD_ENABLED", "true")).lower()
        wake_enabled = wake_enabled_str not in ("false", "0", "no", "off")

        metrics_enabled_str = str(get_val("NEURON_METRICS_ENABLED", "true")).lower()
        metrics_enabled = metrics_enabled_str not in ("false", "0", "no", "off")

        return cls(
            llm_provider=get_val("LLM_PROVIDER", "gemini"),
            gemini_api_key=gemini_key,
            gemini_model=get_val("GEMINI_MODEL", "gemini-2.5-flash"),
            stt_provider=get_val("STT_PROVIDER", "whisper"),
            whisper_model=get_val("WHISPER_MODEL", "base.en"),
            tts_provider=get_val("TTS_PROVIDER", "elevenlabs"),
            elevenlabs_api_key=eleven_key,
            elevenlabs_voice_id=voice_id,
            elevenlabs_model_id=get_val("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5"),
            wake_word_enabled=wake_enabled,
            wake_word_phrase=get_val("NEURON_WAKE_WORD_PHRASE", "Hey Neuron"),
            demo_mode=get_val("NEURON_DEMO_MODE", "auto"),
            demo_scenario=get_val("NEURON_DEMO_SCENARIO", None),
            metrics_enabled=metrics_enabled,
            log_level=get_val("LOG_LEVEL", "INFO"),
        )

    def has_required_credentials(self) -> bool:
        """Return True if required provider credentials (Gemini & ElevenLabs) are present."""
        has_gemini = bool(self.gemini_api_key and self.gemini_api_key.strip())
        has_eleven = bool(self.elevenlabs_api_key and self.elevenlabs_api_key.strip())
        return has_gemini and has_eleven

    # Alias for convenience
    load = from_env

    def __repr__(self) -> str:
        """Secret-safe string representation of settings."""
        return (
            f"NeuronSettings("
            f"llm_provider='{self.llm_provider}', "
            f"gemini_api_key='{_mask_secret(self.gemini_api_key)}', "
            f"gemini_model='{self.gemini_model}', "
            f"stt_provider='{self.stt_provider}', "
            f"whisper_model='{self.whisper_model}', "
            f"tts_provider='{self.tts_provider}', "
            f"elevenlabs_api_key='{_mask_secret(self.elevenlabs_api_key)}', "
            f"elevenlabs_voice_id='{self.elevenlabs_voice_id}', "
            f"elevenlabs_model_id='{self.elevenlabs_model_id}', "
            f"wake_word_enabled={self.wake_word_enabled}, "
            f"wake_word_phrase='{self.wake_word_phrase}', "
            f"demo_mode='{self.demo_mode}', "
            f"demo_scenario='{self.demo_scenario}', "
            f"metrics_enabled={self.metrics_enabled}, "
            f"log_level='{self.log_level}')"
        )


_cached_settings: Optional[NeuronSettings] = None


def get_settings(reload: bool = False) -> NeuronSettings:
    """Return the global cached NeuronSettings instance."""
    global _cached_settings
    if _cached_settings is None or reload:
        _cached_settings = NeuronSettings.from_env()
    return _cached_settings
