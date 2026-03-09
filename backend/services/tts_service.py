"""
services/tts_service.py
Text-to-Speech service using Cartesia.
All TTS logic lives here — controllers just call speak().
"""
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("VoiceAI.TTS")

# Cartesia voice ID — change here to swap voices globally
VOICE_ID = "a0e99841-438c-4a64-b679-ae501e7d6091"
TTS_MODEL = "sonic-multilingual"   # supports EN, HI, TA


class TTSService:
    def __init__(self):
        self._client = None
        self._init_client()

    def _init_client(self):
        api_key = os.getenv("CARTESIA_API_KEY")
        if not api_key:
            logger.warning("[TTS] CARTESIA_API_KEY not set. TTS disabled.")
            return
        try:
            from cartesia import Cartesia
            self._client = Cartesia(api_key=api_key)
            logger.info("[TTS] Cartesia client initialized.")
        except Exception as e:
            logger.error(f"[TTS] Failed to initialize Cartesia: {e}")

    @property
    def available(self) -> bool:
        return self._client is not None

    async def synthesize(self, text: str) -> Optional[bytes]:
        """
        Convert text to WAV audio bytes.
        Runs the synchronous Cartesia call in a thread to avoid blocking the event loop.
        Returns None if TTS is unavailable or synthesis fails.
        """
        if not self.available or not text.strip():
            return None
        try:
            audio_bytes = await asyncio.to_thread(
                lambda: b"".join(self._client.tts.bytes(
                    model_id=TTS_MODEL,
                    transcript=text,
                    voice={"mode": "id", "id": VOICE_ID},
                    output_format={
                        "container": "wav",
                        "encoding": "pcm_s16le",
                        "sample_rate": 44100,
                    },
                ))
            )
            logger.info(f"[TTS] Synthesized {len(audio_bytes):,} bytes for: '{text[:60]}...'")
            return audio_bytes
        except Exception as e:
            logger.error(f"[TTS] Synthesis failed: {e}")
            return None


# Singleton — import and use directly
tts_service = TTSService()
