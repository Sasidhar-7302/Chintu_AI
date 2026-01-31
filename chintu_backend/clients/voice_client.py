"""Voice client that connects to the Gateway (Phase 1)."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..core.config import get_config
from ..audio import AudioCapture, WakeWordDetector, SpeechToText
from ..gateway import GatewayClient

logger = logging.getLogger(__name__)


class VoiceClient:
    """Standalone voice client for Gateway-based command handling."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, token: Optional[str] = None):
        self.config = get_config()
        self.host = host or self.config.gateway_host
        self.port = port or self.config.gateway_port
        self.token = token or self.config.gateway_auth_token

        self.gateway = GatewayClient(host=self.host, port=self.port, token=self.token)
        self.audio_capture = AudioCapture(
            sample_rate=self.config.audio_sample_rate,
            channels=self.config.audio_channels,
            chunk_size=self.config.audio_chunk_size,
        )
        self.wake_word = WakeWordDetector(
            wake_word=self.config.wake_word,
            sensitivity=self.config.wake_word_sensitivity,
            sample_rate=self.config.audio_sample_rate,
            model_path=self.config.wake_word_model_path,
            base_model=self.config.wake_word_base_model,
            backend=self.config.wake_word_backend,
            verifier_path=str(self.config.wake_word_verifier_path)
            if self.config.wake_word_verifier_path
            else None,
            verifier_threshold=self.config.wake_word_verifier_threshold,
            match_threshold=self.config.wake_word_match_threshold,
            require_prefix=self.config.wake_word_require_prefix,
            stt_model_name=self.config.wake_word_stt_model,
            cooldown_seconds=self.config.wake_word_cooldown_seconds,
            activation_frames=self.config.wake_word_activation_frames,
            confirm_with_stt=self.config.wake_word_confirm_with_stt,
            confirm_window_seconds=self.config.wake_word_confirm_window_seconds,
            stt_confidence_threshold=self.config.wake_word_stt_confidence_threshold,
            noise_mode=self.config.wake_word_noise_mode,
            min_word_count=self.config.wake_word_min_word_count,
        )
        self.stt = SpeechToText(
            model_name=self.config.whisper_model,
            device=self.config.whisper_device,
            language=self.config.whisper_language,
            silence_threshold=self.config.stt_silence_threshold,
            silence_duration=self.config.stt_silence_duration,
            vad_filter=self.config.stt_vad_filter,
            partial_interval=self.config.stt_partial_interval,
            partial_window_seconds=self.config.stt_partial_window_seconds,
            initial_prompt=self.config.stt_initial_prompt,
            timeout_seconds=self.config.stt_timeout_seconds,
            min_listen_seconds=self.config.stt_min_listen_seconds,
            min_confidence=self.config.stt_min_confidence,
            speech_frames_required=self.config.stt_speech_frames_required,
            compute_type=self.config.stt_compute_type,
            cpu_threads=self.config.stt_cpu_threads,
            num_workers=self.config.stt_num_workers,
            beam_size=self.config.stt_beam_size,
            best_of=self.config.stt_best_of,
            partial_beam_size=self.config.stt_partial_beam_size,
        )

        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        def on_wake():
            if not self.stt.is_listening:
                self.stt.start_listening()

        async def on_transcript(text: str):
            if not text:
                return
            try:
                await self.gateway.handle_text(text, source="voice_client")
            except Exception as exc:
                logger.warning("Gateway send failed: %s", exc)

        def on_text(text: str):
            asyncio.run_coroutine_threadsafe(on_transcript(text), self._loop)

        self.wake_word.set_callback(on_wake)
        self.stt.set_callback(on_text)

    async def start(self) -> None:
        logger.info("VoiceClient starting...")
        self._running = True
        self._loop = asyncio.get_running_loop()
        await self.gateway.connect()
        self.audio_capture.start()
        self.wake_word.start()
        logger.info("VoiceClient ready (wake word active)")

    async def stop(self) -> None:
        logger.info("VoiceClient stopping...")
        self._running = False
        try:
            self.wake_word.stop()
            self.audio_capture.stop()
        except Exception:
            pass
        await self.gateway.close()
        logger.info("VoiceClient stopped")
