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
    TTSNetworkError,
    TTSQuotaExceededError,
    TTSError,
    TTSTimeoutError,
)
from app.tts.model import TTSAudioClip

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (clear, pedagogical)
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"      # High quality, low latency, free-tier compatible
DEFAULT_OUTPUT_FORMAT = "pcm_24000"        # 24kHz 16-bit mono raw PCM


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
        self._voice_id: str = voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
        self._model_id: str = model_id or os.environ.get("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID
        self._output_format: str = output_format or DEFAULT_OUTPUT_FORMAT
        self._timeout_seconds: float = timeout_seconds
        self._session: requests.Session = session or requests.Session()
        self._cache: Dict[str, TTSAudioClip] = {}

    @property
    def voice_id(self) -> str:
        return self._voice_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def output_format(self) -> str:
        return self._output_format

    def _resolve_api_key(self) -> str:
        """Resolve API key lazily from explicit config, environment variables, or .env file."""
        key = self._explicit_api_key or os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("TTS_API_KEY")
        if not key:
            env_path = os.path.join(os.getcwd(), ".env")
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("ELEVENLABS_API_KEY="):
                                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                                if candidate:
                                    key = candidate
                                    break
                            elif line.startswith("TTS_API_KEY="):
                                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                                if candidate:
                                    key = candidate
                                    break
                except Exception:
                    pass

        if not key or not key.strip():
            raise TTSAuthenticationError(
                "ElevenLabs API key is missing. Set ELEVENLABS_API_KEY or TTS_API_KEY environment variable."
            )
        return key.strip()

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

    def synthesize(self, text: str) -> TTSAudioClip:
        """Synthesize text into in-memory PCM audio using ElevenLabs.

        Employs in-memory caching to avoid redundant API consumption and costs.
        """
        clean_text = text.strip() if text else ""
        if not clean_text:
            return TTSAudioClip(
                raw_bytes=b"",
                sample_rate=self._determine_sample_rate(),
                duration_seconds=0.0,
                text="",
            )

        # Check in-memory cache
        cache_key = f"{self._voice_id}:{self._model_id}:{clean_text}"
        if cache_key in self._cache:
            logger.debug("Returning cached TTS audio clip for text: %s", clean_text[:40])
            return self._cache[cache_key]

        api_key = self._resolve_api_key()
        sample_rate = self._determine_sample_rate()

        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
            f"?output_format={self._output_format}"
        )
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/*",
        }
        payload = {
            "text": clean_text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        logger.info(
            "Requesting ElevenLabs TTS (voice=%s, model=%s, text_length=%d)",
            self._voice_id,
            self._model_id,
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
            raise TTSAuthenticationError(
                "ElevenLabs authentication failed (HTTP 401): invalid API key."
            )
        if response.status_code == 429:
            raise TTSQuotaExceededError(
                "ElevenLabs quota exceeded or rate limit reached (HTTP 429)."
            )
        if response.status_code == 400:
            err_body = response.text
            if "quota" in err_body.lower():
                raise TTSQuotaExceededError(f"ElevenLabs quota exceeded: {err_body}")
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
