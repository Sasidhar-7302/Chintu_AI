"""Wake word training and sample recording."""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
import wave

import numpy as np

try:
    import openwakeword
    from openwakeword.custom_verifier_model import (
        get_reference_clip_features,
        train_verifier_model,
    )
    HAS_OPENWAKEWORD = True
except ImportError:
    HAS_OPENWAKEWORD = False

from .audio_capture import AudioCapture

logger = logging.getLogger(__name__)


@dataclass
class WakeWordStatus:
    samples: List[bool]
    count: int


class WakeWordTrainer:
    """Records wake word samples and trains a custom verifier."""

    def __init__(self, audio_capture: AudioCapture, config):
        self.audio_capture = audio_capture
        self.config = config
        self.samples_dir = Path(config.wake_word_samples_dir)
        self.positive_dir = self.samples_dir / "positive"
        self.negative_dir = self.samples_dir / "negative"
        self.verifier_path = Path(config.wake_word_verifier_path)
        self.sample_count = config.wake_word_sample_count
        self.sample_duration = config.wake_word_sample_duration
        self.base_model = config.wake_word_base_model
        self.threshold = config.wake_word_verifier_threshold

        self.positive_dir.mkdir(parents=True, exist_ok=True)
        self.negative_dir.mkdir(parents=True, exist_ok=True)

    def _sample_path(self, index: int, kind: str) -> Path:
        filename = f"{kind}_{index:02d}.wav"
        return (self.positive_dir if kind == "positive" else self.negative_dir) / filename

    def record_sample(self, index: int, kind: str = "positive") -> Path:
        if index < 1 or index > self.sample_count:
            raise ValueError(f"Index must be 1-{self.sample_count}")
        if kind not in ("positive", "negative"):
            raise ValueError("Kind must be positive or negative")
        if not self.audio_capture.is_running:
            raise RuntimeError("Audio capture is not running")

        audio = self.audio_capture.record_samples(self.sample_duration)
        audio = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio * 32767).astype(np.int16)

        path = self._sample_path(index, kind)
        self._write_wav(path, audio_int16)
        return path

    def record_background_samples(
        self,
        count: Optional[int] = None,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        if count is None:
            count = self.sample_count

        recorded = 0
        for i in range(1, count + 1):
            path = self._sample_path(i, "negative")
            if path.exists():
                recorded += 1
                continue
            self.record_sample(i, "negative")
            recorded += 1
            if progress:
                progress(recorded, count)
        return recorded

    def get_status(self) -> WakeWordStatus:
        samples = []
        for i in range(1, self.sample_count + 1):
            samples.append(self._sample_path(i, "positive").exists())
        return WakeWordStatus(samples=samples, count=self.sample_count)

    def _ensure_openwakeword_models(self) -> None:
        if not HAS_OPENWAKEWORD:
            return
        try:
            from openwakeword.utils import download_models
        except Exception as exc:
            logger.debug(f"openWakeWord download helpers unavailable: {exc}")
            return

        try:
            target_name = self.base_model if self.base_model in openwakeword.MODELS else None

            missing_feature = any(
                not os.path.exists(meta["model_path"])
                for meta in list(openwakeword.FEATURE_MODELS.values())
                + list(openwakeword.VAD_MODELS.values())
            )
            missing_base = False
            if target_name:
                model_path = openwakeword.MODELS[target_name]["model_path"]
                missing_base = (
                    not os.path.exists(model_path)
                    or not os.path.exists(model_path.replace(".tflite", ".onnx"))
                )

            if missing_feature or missing_base:
                download_target = target_name or "hey_jarvis"
                logger.info(f"Downloading openWakeWord assets for '{download_target}'...")
                download_models([download_target])
        except Exception as exc:
            logger.warning(f"Failed to download openWakeWord models: {exc}")

    def train_verifier(self, progress: Optional[Callable[[str, str], None]] = None) -> Path:
        if not HAS_OPENWAKEWORD:
            raise RuntimeError("openwakeword is not installed")

        self._ensure_openwakeword_models()

        positive_files = [
            str(self._sample_path(i, "positive"))
            for i in range(1, self.sample_count + 1)
            if self._sample_path(i, "positive").exists()
        ]
        if len(positive_files) < self.sample_count:
            raise RuntimeError("Not enough positive samples recorded")

        negative_files = [
            str(self._sample_path(i, "negative"))
            for i in range(1, self.sample_count + 1)
            if self._sample_path(i, "negative").exists()
        ]
        if len(negative_files) < self.sample_count:
            if progress:
                progress("recording_background", "Recording background samples. Stay quiet.")
            self.record_background_samples(self.sample_count)
            negative_files = [
                str(self._sample_path(i, "negative"))
                for i in range(1, self.sample_count + 1)
                if self._sample_path(i, "negative").exists()
            ]

        if progress:
            progress("training", "Training wake word verifier.")

        model_key = self._model_key(self.base_model)
        oww = openwakeword.Model(wakeword_models=[self.base_model], inference_framework="onnx")

        positive_features = np.vstack(
            [
                get_reference_clip_features(
                    clip,
                    oww,
                    model_key,
                    threshold=self.threshold,
                    N=3,
                )
                for clip in positive_files
            ]
        )
        if positive_features.shape[0] == 0:
            if progress:
                progress(
                    "training",
                    "Base model did not activate. Retrying with a lower threshold.",
                )
            positive_features = np.vstack(
                [
                    get_reference_clip_features(
                        clip,
                        oww,
                        model_key,
                        threshold=0.0,
                        N=3,
                    )
                    for clip in positive_files
                ]
            )
        if positive_features.shape[0] == 0:
            if progress:
                progress(
                    "training",
                    "Still no activation. Using broader feature capture.",
                )
            positive_features = np.vstack(
                [
                    get_reference_clip_features(
                        clip,
                        oww,
                        model_key,
                        threshold=-1.0,
                        N=1,
                    )
                    for clip in positive_files
                ]
            )
        if positive_features.shape[0] == 0:
            raise RuntimeError(
                "Wake word samples could not be processed. Try recording again in a quiet room."
            )

        negative_features = np.vstack(
            [
                get_reference_clip_features(
                    clip,
                    oww,
                    model_key,
                    threshold=0.0,
                    N=1,
                )
                for clip in negative_files
            ]
        )

        lr_model = train_verifier_model(
            np.vstack((positive_features, negative_features)),
            np.array([1] * positive_features.shape[0] + [0] * negative_features.shape[0]),
        )

        self.verifier_path.parent.mkdir(parents=True, exist_ok=True)
        pickle.dump(lr_model, open(self.verifier_path, "wb"))
        return self.verifier_path

    @staticmethod
    def _model_key(model_name: str) -> str:
        if os.path.exists(model_name):
            return os.path.splitext(os.path.basename(model_name))[0]
        return model_name

    @staticmethod
    def _write_wav(path: Path, audio: np.ndarray) -> None:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio.tobytes())
