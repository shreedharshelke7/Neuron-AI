"""ElevenLabs Text-to-Speech (TTS) adapter for Block 5.

Communicates with the ElevenLabs REST API to synthesize educational narration
into high-fidelity in-memory PCM audio.
Zero disk persistence; lazy credential resolution; cost-controlled caching.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

from app.tts.adapter import TTSAdapter
from app.tts.errors import (
    TTSAuthenticationError,
    TTSConfigurationError,
    TTSError,
    TTSNetworkError,
    TTSPaidPlanRequiredError,
    TTSQuotaExceededError,
    TTSTimeoutError,
    is_terminal_tts_error,
)
from app.tts.model import TTSAudioClip

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "eleven_turbo_v2_5"      # High quality, low latency, free-tier compatible
DEFAULT_OUTPUT_FORMAT = "pcm_24000"        # 24kHz 16-bit mono raw PCM


def _read_env_file_var(var_name: str) -> Optional[str]:
    """Safely search workspace .env file for a variable without side-effects."""
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line or "=" not in line:
                        continue
                    k, val = line.split("=", 1)
                    if k.strip() == var_name:
                        cleaned = val.strip().strip('"').strip("'")
                        if cleaned:
                            return cleaned
        except Exception:
            pass
    return None


class ElevenLabsTTSAdapter(TTSAdapter):
    """Production TTS adapter integrating with ElevenLabs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        output_format: Optional[str] = None,
        timeout_seconds: float = 15.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._explicit_api_key: Optional[str] = api_key
        self._explicit_voice_id: Optional[str] = voice_id
        self._explicit_model_id: Optional[str] = model_id
        self._output_format: str = output_format or DEFAULT_OUTPUT_FORMAT
        self._timeout_seconds: float = timeout_seconds
        self._session: requests.Session = session or requests.Session()
        self._cache: Dict[str, TTSAudioClip] = {}
        self._terminal_error: Optional[Exception] = None

    @property
    def voice_id(self) -> Optional[str]:
        """Return the resolved voice ID if configured, or None."""
        return self._resolve_voice_id_optional()

    @property
    def model_id(self) -> str:
        """Return the resolved model ID."""
        return self._resolve_model_id()

    @property
    def output_format(self) -> str:
        return self._output_format

    def _resolve_voice_id_optional(self) -> Optional[str]:
        """Resolve voice ID without raising if missing."""
        if self._explicit_voice_id and self._explicit_voice_id.strip():
            return self._explicit_voice_id.strip()
        val = os.environ.get("ELEVENLABS_VOICE_ID") or os.environ.get("TTS_VOICE_ID")
        if val and val.strip():
            return val.strip()
        env_val = _read_env_file_var("ELEVENLABS_VOICE_ID") or _read_env_file_var("TTS_VOICE_ID")
        if env_val and env_val.strip():
            return env_val.strip()
        return None

    def _resolve_voice_id(self) -> str:
        """Resolve voice ID or raise clear TTSConfigurationError.

        Prevents silently falling back to a paid library voice that breaks free-tier users.
        """
        vid = self._resolve_voice_id_optional()
        if not vid:
            raise TTSConfigurationError(
                "ELEVENLABS_VOICE_ID is not configured. "
                "Set ELEVENLABS_VOICE_ID in your environment or .env file with your free-tier compatible voice ID "
                "(e.g. created in ElevenLabs VoiceLab)."
            )
        return vid

    def _resolve_api_key(self) -> str:
        """Resolve API key lazily from explicit config, environment variables, or .env file."""
        key = self._explicit_api_key or os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("TTS_API_KEY")
        if not key:
            key = _read_env_file_var("ELEVENLABS_API_KEY") or _read_env_file_var("TTS_API_KEY")

        if not key or not key.strip():
            raise TTSAuthenticationError(
                "ElevenLabs API key is missing. Set ELEVENLABS_API_KEY in your environment or .env file."
            )
        return key.strip()

    def _resolve_model_id(self) -> str:
        """Resolve model ID from explicit config, environment, .env, or default."""
        if self._explicit_model_id and self._explicit_model_id.strip():
            return self._explicit_model_id.strip()
        val = os.environ.get("ELEVENLABS_MODEL_ID")
        if val and val.strip():
            return val.strip()
        env_val = _read_env_file_var("ELEVENLABS_MODEL_ID")
        if env_val and env_val.strip():
            return env_val.strip()
        return DEFAULT_MODEL_ID

    def _determine_sample_rate(self) -> int:
        """Determine sample rate from output_format parameter."""
        fmt = self._output_format.lower()
        if "pcm_24000" in fmt:
            return 24000
        if "pcm_16000" in fmt:
            return 16000
        if "pcm_44100" in fmt:
            return 44100
        if "pcm_22050" in fmt:
            return 22050
        return 24000

    def reset_terminal_error(self) -> None:
        """Clear the circuit breaker after configuration update or new session."""
        self._terminal_error = None

    def synthesize(self, text: str) -> TTSAudioClip:
        """Synthesize text into in-memory PCM audio using ElevenLabs.

        Employs in-memory caching to avoid redundant API consumption and costs.
        Enforces a circuit breaker on terminal provider errors (e.g. HTTP 402/401/config)
        to prevent burning quota or spamming provider requests segment-by-segment.
        """
        # Circuit breaker: halt immediately if previous call in this session failed terminally
        if self._terminal_error is not None:
            logger.debug(
                "Circuit breaker active: skipping ElevenLabs call due to prior terminal error: %s",
                self._terminal_error,
            )
            raise self._terminal_error

        clean_text = text.strip() if text else ""
        if not clean_text:
            return TTSAudioClip(
                raw_bytes=b"",
                sample_rate=self._determine_sample_rate(),
                duration_seconds=0.0,
                text="",
            )

        # Validate configuration before making request
        try:
            voice_id = self._resolve_voice_id()
            api_key = self._resolve_api_key()
        except Exception as config_err:
            self._terminal_error = config_err
            raise config_err

        model_id = self._resolve_model_id()

        # Check in-memory cache
        cache_key = f"{voice_id}:{model_id}:{clean_text}"
        if cache_key in self._cache:
            logger.debug("Returning cached TTS audio clip for text: %s", clean_text[:40])
            return self._cache[cache_key]

        sample_rate = self._determine_sample_rate()

        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            f"?output_format={self._output_format}"
        )
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/*",
        }
        payload = {
            "text": clean_text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        logger.info(
            "Requesting ElevenLabs TTS (voice=%s, model=%s, text_length=%d)",
            voice_id,
            model_id,
            len(clean_text),
        )

        try:
            response = self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except requests.exceptions.Timeout as err:
            logger.error("ElevenLabs request timed out after %.1fs", self._timeout_seconds)
            raise TTSTimeoutError(f"ElevenLabs TTS request timed out: {err}") from err
        except requests.exceptions.ConnectionError as err:
            logger.error("ElevenLabs network connection error: %s", err)
            raise TTSNetworkError(f"ElevenLabs connection failure: {err}") from err
        except requests.exceptions.RequestException as err:
            logger.error("ElevenLabs request exception: %s", err)
            raise TTSError(f"ElevenLabs request error: {err}") from err

        # Error response normalization
        if response.status_code == 401:
            err = TTSAuthenticationError(
                "ElevenLabs authentication failed (HTTP 401): invalid API key."
            )
            self._terminal_error = err
            raise err

        if response.status_code == 402:
            err = TTSPaidPlanRequiredError(
                "ElevenLabs paid plan required for this voice. Free users cannot use library voices via the API. "
                "Please configure a free-tier compatible voice ID via ELEVENLABS_VOICE_ID.",
                details=response.text,
            )
            self._terminal_error = err
            raise err

        if response.status_code == 429:
            err = TTSQuotaExceededError(
                "ElevenLabs quota exceeded or rate limit reached (HTTP 429)."
            )
            self._terminal_error = err
            raise err

        if response.status_code == 400:
            err_body = response.text
            err_body_lower = err_body.lower()
            if "paid_plan_required" in err_body_lower:
                err = TTSPaidPlanRequiredError(
                    "ElevenLabs paid plan required for this voice. Free users cannot use library voices via the API. "
                    "Please configure a free-tier compatible voice ID via ELEVENLABS_VOICE_ID.",
                    details=err_body,
                )
                self._terminal_error = err
                raise err
            if "quota" in err_body_lower:
                err = TTSQuotaExceededError(f"ElevenLabs quota exceeded: {err_body}")
                self._terminal_error = err
                raise err
            if "voice" in err_body_lower:
                err = TTSConfigurationError(f"ElevenLabs voice configuration error: {err_body}")
                self._terminal_error = err
                raise err
            raise TTSError(f"ElevenLabs bad request (HTTP 400): {err_body}")

        if response.status_code in (408, 504):
            raise TTSTimeoutError(f"ElevenLabs request timed out (HTTP {response.status_code}).")

        if response.status_code >= 500:
            raise TTSNetworkError(
                f"ElevenLabs server error (HTTP {response.status_code}): {response.text}"
            )

        if not response.ok:
            raise TTSError(
                f"ElevenLabs synthesis failed (HTTP {response.status_code}): {response.text}"
            )

        raw_bytes = response.content
        if not raw_bytes:
            logger.warning("ElevenLabs returned empty audio payload.")
            return TTSAudioClip(
                raw_bytes=b"",
                sample_rate=sample_rate,
                duration_seconds=0.0,
                text=clean_text,
            )

        # 16-bit signed mono PCM: 2 bytes per sample
        duration = len(raw_bytes) / float(sample_rate * 2)

        clip = TTSAudioClip(
            raw_bytes=raw_bytes,
            sample_rate=sample_rate,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
            duration_seconds=duration,
            text=clean_text,
        )

        self._cache[cache_key] = clip
        logger.info(
            "Synthesized narration audio: %.2fs (%d bytes, %dHz)",
            duration,
            len(raw_bytes),
            sample_rate,
        )
        return clip

    def clear_cache(self) -> None:
        """Clear the in-memory synthesis cache."""
        self._cache.clear()
