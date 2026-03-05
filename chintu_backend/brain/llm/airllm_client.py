"""Optional AirLLM client for very large local text models.

This module is intentionally dependency-optional:
- If `airllm` is not installed, it raises a clear runtime error when used.
- Router code can catch failures and fall back to Ollama/cloud providers.
"""

from __future__ import annotations

import atexit
import gc
import importlib
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import types
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


class AirLLMClient:
    """Best-effort AirLLM wrapper with a Chintu-compatible interface."""
    _WORKER_RESPONSE_PREFIX = "CHINTU_AIRLLM_JSON:"
    _WORKER_EOF_SENTINEL = "__CHINTU_AIRLLM_WORKER_EOF__"

    def __init__(
        self,
        *,
        model_id: str,
        cache_dir: Optional[Path] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        compression: str = "auto",
        device: str = "auto",
        allow_download: bool = False,
        download_timeout_seconds: int = 3600,
        runtime_mode: str = "auto",
        request_timeout_seconds: int = 900,
        startup_timeout_seconds: int = 1800,
    ) -> None:
        self.model = str(model_id or "").strip()
        self.model_name = self.model
        self.cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir else None
        self.max_tokens = int(max_tokens or 2048)
        self.temperature = float(temperature)
        self.compression = str(compression or "auto").strip().lower()
        self.device = str(device or "auto").strip().lower()
        self.allow_download = bool(allow_download)
        self.download_timeout_seconds = max(60, int(download_timeout_seconds or 3600))
        self.runtime_mode = str(runtime_mode or "auto").strip().lower()
        self.request_timeout_seconds = max(30, int(request_timeout_seconds or 900))
        self.startup_timeout_seconds = max(60, int(startup_timeout_seconds or 1800))
        self._available = bool(self.model)
        self._load_error = ""
        self._model: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None
        self._lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._worker_process: Optional[subprocess.Popen[str]] = None
        self._worker_queue: Optional[queue.Queue[str]] = None
        self._worker_reader_thread: Optional[threading.Thread] = None
        self._worker_log_tail: deque[str] = deque(maxlen=64)
        self._worker_atexit_registered = False

    @property
    def is_available(self) -> bool:
        return bool(self._available and self.model)

    @property
    def last_error(self) -> str:
        return str(self._load_error or "")

    def _use_subprocess_mode(self) -> bool:
        mode = str(self.runtime_mode or "auto").strip().lower()
        if mode in {"subprocess", "process", "worker"}:
            return True
        if mode in {"inprocess", "inline", "off", "disabled"}:
            return False
        # Auto mode: isolate native crashes on Windows.
        return os.name == "nt"

    def _build_prompt(self, prompt: str, system_prompt: Optional[str]) -> str:
        prompt = str(prompt or "")
        system_prompt = str(system_prompt or "").strip()
        if system_prompt:
            return f"System: {system_prompt}\nUser: {prompt}\nAssistant:"
        return f"User: {prompt}\nAssistant:"

    @staticmethod
    def _install_optimum_bettertransformer_shim() -> None:
        """Install a lightweight shim when optimum.bettertransformer is unavailable.

        AirLLM imports BetterTransformer at module import time. On newer
        transformers versions this can raise runtime compatibility errors.
        The shim keeps AirLLM importable and lets unsupported models fall back
        to sdpa/no-BetterTransformer code paths.
        """
        try:
            importlib.import_module("optimum.bettertransformer")
            return
        except Exception:
            pass

        shim = types.ModuleType("optimum.bettertransformer")

        class _BetterTransformer:  # pragma: no cover - tiny compat shim
            @staticmethod
            def transform(model, *args, **kwargs):
                return model

        shim.BetterTransformer = _BetterTransformer  # type: ignore[attr-defined]
        optimum_pkg = sys.modules.get("optimum")
        if optimum_pkg is None:
            optimum_pkg = types.ModuleType("optimum")
            sys.modules["optimum"] = optimum_pkg
        setattr(optimum_pkg, "bettertransformer", shim)
        sys.modules["optimum.bettertransformer"] = shim

    @staticmethod
    def _patch_airllm_qwen3_mapping() -> None:
        """Map Qwen3/Qwen3.5 architectures to AirLLM's Qwen2 backend."""
        try:
            airllm_mod = importlib.import_module("airllm")
            if not hasattr(airllm_mod, "AirLLMQWen3_5"):
                base_cls = getattr(airllm_mod, "AirLLMBaseModel", None)

                if base_cls is not None:
                    class AirLLMQWen3_5(base_cls):  # pragma: no cover - runtime compat class
                        def set_layer_names_dict(self):
                            self.layer_names_dict = {
                                "embed": "model.language_model.embed_tokens",
                                "layer_prefix": "model.language_model.layers",
                                "norm": "model.language_model.norm",
                                "lm_head": "lm_head",
                            }

                        def get_use_better_transformer(self):
                            return False

                        def _resolve_path(self, dotted: str):
                            target = self.model
                            for part in str(dotted or "").split("."):
                                if not part:
                                    continue
                                if hasattr(target, part):
                                    target = getattr(target, part)
                                    continue
                                if part == "language_model":
                                    # Qwen3.5 text checkpoints expose model.* instead of
                                    # model.language_model.* in instantiated modules.
                                    continue
                                raise AttributeError(f"Missing attribute '{part}' while resolving '{dotted}'")
                            return target

                        def set_layers_from_layer_names(self):
                            self.layers = []
                            self.layers.append(self._resolve_path(self.layer_names_dict["embed"]))
                            layer_group = self._resolve_path(self.layer_names_dict["layer_prefix"])
                            self.layers.extend(list(layer_group))
                            self.layers.append(self._resolve_path(self.layer_names_dict["norm"]))
                            self.layers.append(self._resolve_path(self.layer_names_dict["lm_head"]))

                        @staticmethod
                        def _remap_param_name(param_name: str) -> str:
                            if ".language_model." in str(param_name):
                                return str(param_name).replace(".language_model.", ".", 1)
                            return str(param_name)

                        def move_layer_to_device(self, state_dict):
                            base_mod = importlib.import_module("airllm.airllm_base")
                            set_tensor = getattr(base_mod, "set_module_tensor_to_device")

                            moved_layers = []
                            for original_name, tensor in state_dict.items():
                                target_name = self._remap_param_name(original_name)
                                moved_layers.append(target_name)
                                if self.hf_quantizer is None:
                                    set_tensor(
                                        self.model,
                                        target_name,
                                        self.running_device,
                                        value=tensor,
                                        dtype=self.running_dtype,
                                    )
                                    continue
                                if not self.hf_quantizer.check_quantized_param(
                                    self.model,
                                    param_value=None,
                                    param_name=target_name,
                                    state_dict={},
                                ):
                                    set_tensor(
                                        self.model,
                                        target_name,
                                        self.running_device,
                                        value=tensor,
                                        dtype=self.running_dtype,
                                    )
                                else:
                                    self.hf_quantizer.create_quantized_param(
                                        self.model,
                                        tensor,
                                        target_name,
                                        self.running_device,
                                        state_dict,
                                    )
                            return moved_layers

                        def init_model(self):
                            cfg = getattr(self, "config", None)
                            text_cfg = getattr(cfg, "text_config", None)
                            if cfg is not None and text_cfg is not None:
                                bridge_fields = (
                                    "vocab_size",
                                    "hidden_size",
                                    "intermediate_size",
                                    "num_hidden_layers",
                                    "num_attention_heads",
                                    "num_key_value_heads",
                                    "max_position_embeddings",
                                    "rms_norm_eps",
                                    "rope_theta",
                                    "tie_word_embeddings",
                                    "bos_token_id",
                                    "eos_token_id",
                                    "pad_token_id",
                                )
                                for field in bridge_fields:
                                    target_value = getattr(cfg, field, None)
                                    if target_value is not None:
                                        continue
                                    source_value = getattr(text_cfg, field, None)
                                    if source_value is not None:
                                        setattr(cfg, field, source_value)
                                try:
                                    text_items = dict(getattr(text_cfg, "to_dict", lambda: {})() or {})
                                except Exception:
                                    text_items = {}
                                for field, source_value in text_items.items():
                                    if not isinstance(field, str) or field.startswith("_"):
                                        continue
                                    if source_value is None:
                                        continue
                                    target_value = getattr(cfg, field, None)
                                    if target_value is None:
                                        setattr(cfg, field, source_value)
                                if getattr(cfg, "eos_token_id", None) is None:
                                    eos_value = getattr(text_cfg, "eos_token_id", None)
                                    if eos_value is not None:
                                        setattr(cfg, "eos_token_id", eos_value)
                                if getattr(cfg, "pad_token_id", None) is None:
                                    pad_value = getattr(text_cfg, "pad_token_id", None)
                                    if pad_value is None:
                                        pad_value = getattr(cfg, "eos_token_id", None)
                                    if pad_value is None:
                                        pad_value = 0
                                    setattr(cfg, "pad_token_id", pad_value)
                            return super().init_model()

                    setattr(airllm_mod, "AirLLMQWen3_5", AirLLMQWen3_5)

            auto_model_mod = importlib.import_module("airllm.auto_model")
            auto_cls = getattr(auto_model_mod, "AutoModel", None)
            if auto_cls is None or getattr(auto_cls, "_chintu_qwen3_patch", False):
                return
            original = auto_cls.get_module_class

            def _patched_get_module_class(cls, pretrained_model_name_or_path, *inputs, **kwargs):
                try:
                    from transformers import AutoConfig

                    token = kwargs.get("hf_token")
                    if token:
                        config = AutoConfig.from_pretrained(
                            pretrained_model_name_or_path,
                            trust_remote_code=True,
                            token=token,
                        )
                    else:
                        config = AutoConfig.from_pretrained(
                            pretrained_model_name_or_path,
                            trust_remote_code=True,
                        )
                    architectures = list(getattr(config, "architectures", []) or [])
                    arch = str(architectures[0] if architectures else "")
                    if "Qwen3" in arch or "qwen3" in arch:
                        return "airllm", "AirLLMQWen3_5"
                except Exception:
                    pass
                return original(pretrained_model_name_or_path, *inputs, **kwargs)

            auto_cls.get_module_class = classmethod(_patched_get_module_class)
            auto_cls._chintu_qwen3_patch = True
        except Exception:
            return

    @staticmethod
    def _patch_airllm_snapshot_download() -> None:
        """Normalize AirLLM snapshot_download kwargs for newer huggingface_hub."""
        try:
            utils_mod = importlib.import_module("airllm.utils")
            hub_mod = getattr(utils_mod, "huggingface_hub", None)
            if hub_mod is None:
                return
            snapshot_download = getattr(hub_mod, "snapshot_download", None)
            if not callable(snapshot_download):
                return
            if getattr(snapshot_download, "_chintu_allow_patterns_patch", False):
                return

            def _patched_snapshot_download(*args, **kwargs):
                allow_patterns = kwargs.get("allow_patterns")
                if isinstance(allow_patterns, str):
                    kwargs["allow_patterns"] = [allow_patterns]
                return snapshot_download(*args, **kwargs)

            _patched_snapshot_download._chintu_allow_patterns_patch = True  # type: ignore[attr-defined]
            hub_mod.snapshot_download = _patched_snapshot_download
        except Exception:
            return

    @staticmethod
    def _patch_airllm_clean_memory() -> None:
        """Avoid unstable CUDA cache calls during Windows CPU-mode layer splitting."""
        try:
            utils_mod = importlib.import_module("airllm.utils")
            clean_memory = getattr(utils_mod, "clean_memory", None)
            if not callable(clean_memory):
                return
            if getattr(utils_mod, "_chintu_clean_memory_patch", False):
                return

            def _patched_clean_memory():
                import gc

                gc.collect()
                if os.name != "nt":
                    try:
                        torch_mod = importlib.import_module("torch")
                        if hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
                            torch_mod.cuda.empty_cache()
                    except Exception:
                        return

            utils_mod.clean_memory = _patched_clean_memory
            utils_mod._chintu_clean_memory_patch = True
        except Exception:
            return

    @staticmethod
    def _cache_model_dir(model_id: str) -> Path:
        safe = str(model_id or "").strip().replace("/", "--")
        return Path.home() / ".cache" / "huggingface" / "hub" / f"models--{safe}"

    @classmethod
    def _latest_snapshot_dir(cls, model_id: str) -> Optional[Path]:
        root = cls._cache_model_dir(model_id) / "snapshots"
        if not root.exists():
            return None
        snapshots = [p for p in root.iterdir() if p.is_dir()]
        if not snapshots:
            return None
        snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return snapshots[0]

    @staticmethod
    def _expected_weight_files(snapshot_path: Path) -> List[str]:
        index_path = snapshot_path / "model.safetensors.index.json"
        if not index_path.exists():
            return []
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            weight_map = payload.get("weight_map", {}) if isinstance(payload, dict) else {}
            files = sorted({str(value) for value in weight_map.values() if isinstance(value, str)})
            return [name for name in files if name.endswith(".safetensors")]
        except Exception:
            return []

    @classmethod
    def _missing_weight_files(cls, snapshot_path: Path) -> List[str]:
        expected = cls._expected_weight_files(snapshot_path)
        missing: List[str] = []
        for name in expected:
            path = snapshot_path / name
            if not path.exists():
                missing.append(name)
                continue
            try:
                if int(path.stat().st_size) <= 0:
                    missing.append(name)
            except Exception:
                missing.append(name)
        return missing

    def _download_missing_weights(self, *, model_id: str, missing_files: List[str], hf_token: str) -> None:
        if not missing_files:
            return
        try:
            hub = importlib.import_module("huggingface_hub")
            hf_hub_download = getattr(hub, "hf_hub_download", None)
            if not callable(hf_hub_download):
                raise RuntimeError("huggingface_hub.hf_hub_download is unavailable.")
        except Exception as exc:
            raise RuntimeError(f"Unable to import huggingface_hub download helper: {exc}") from exc

        started = time.time()
        for index, filename in enumerate(missing_files, start=1):
            elapsed = time.time() - started
            if elapsed > float(self.download_timeout_seconds):
                raise RuntimeError(
                    f"AirLLM shard download timed out after {int(elapsed)}s "
                    f"({index-1}/{len(missing_files)} downloaded)."
                )
            logger.info(
                "AirLLM downloading shard %s/%s: %s",
                index,
                len(missing_files),
                filename,
            )
            kwargs: Dict[str, Any] = {
                "repo_id": model_id,
                "filename": filename,
                "resume_download": True,
            }
            if hf_token:
                kwargs["token"] = hf_token
            hf_hub_download(**kwargs)

    def _resolve_compression_mode(self) -> Optional[str]:
        mode = str(self.compression or "auto").strip().lower()
        if mode in {"none", "off", "false", "0"}:
            return None
        if mode in {"4bit", "8bit"}:
            return mode
        if mode in {"auto", ""}:
            # bitsandbytes on Windows is still unstable in many environments.
            if os.name == "nt":
                return None
            return "4bit"
        return "4bit"

    def _resolve_device_mode(self) -> str:
        mode = str(self.device or "auto").strip().lower()
        if mode and mode != "auto":
            return mode
        if os.name == "nt":
            # Windows GPU stacks for AirLLM are brittle in practice; prefer safe CPU default.
            return "cpu"
        return "cuda:0"

    def _resolve_dtype(self, *, resolved_device: str):
        try:
            torch_mod = importlib.import_module("torch")
        except Exception:
            return None
        device_name = str(resolved_device or "").strip().lower()
        if device_name.startswith("cpu"):
            return getattr(torch_mod, "float32", None)
        return getattr(torch_mod, "float16", None)

    def _resolve_max_seq_len(self) -> int:
        # Keep context practical for large models while preventing runaway RAM usage.
        return max(512, min(2048, int(self.max_tokens or 2048) + 256))

    def _worker_command(self) -> List[str]:
        command = [
            sys.executable,
            "-m",
            "chintu_backend.brain.llm.airllm_worker",
            "--model-id",
            self.model,
            "--max-tokens",
            str(self.max_tokens),
            "--temperature",
            str(self.temperature),
            "--compression",
            str(self.compression or "auto"),
            "--device",
            str(self.device or "auto"),
            "--allow-download",
            "1" if self.allow_download else "0",
            "--download-timeout-seconds",
            str(self.download_timeout_seconds),
        ]
        if self.cache_dir:
            command.extend(["--cache-dir", str(self.cache_dir)])
        return command

    def _worker_stdout_reader(self, process: subprocess.Popen[str]) -> None:
        stream = process.stdout
        if stream is None:
            return
        prefix = self._WORKER_RESPONSE_PREFIX
        local_queue = self._worker_queue
        try:
            for raw_line in stream:
                line = str(raw_line or "").rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(prefix):
                    payload = line[len(prefix) :]
                    if local_queue is not None:
                        local_queue.put(payload)
                    continue
                self._worker_log_tail.append(line)
                logger.debug("AirLLM worker log: %s", line)
        except Exception as exc:
            self._worker_log_tail.append(f"reader_error: {exc}")
        finally:
            if local_queue is not None:
                local_queue.put(self._WORKER_EOF_SENTINEL)

    def _drain_worker_queue(self) -> None:
        local_queue = self._worker_queue
        if local_queue is None:
            return
        while True:
            try:
                local_queue.get_nowait()
            except queue.Empty:
                return

    def _worker_error_tail(self) -> str:
        if not self._worker_log_tail:
            return ""
        return " | ".join(list(self._worker_log_tail)[-6:])

    def _shutdown_worker_locked(self) -> None:
        process = self._worker_process
        self._worker_process = None
        self._worker_queue = None
        self._worker_reader_thread = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=8)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _shutdown_worker(self) -> None:
        with self._worker_lock:
            self._shutdown_worker_locked()

    def _ensure_worker_started_locked(self) -> None:
        process = self._worker_process
        if process is not None and process.poll() is None:
            return
        self._shutdown_worker_locked()
        self._select_cache_dir()
        self._worker_log_tail.clear()
        self._worker_queue = queue.Queue()
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except Exception:
                startupinfo = None
        process = subprocess.Popen(
            self._worker_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        self._worker_process = process
        reader = threading.Thread(target=self._worker_stdout_reader, args=(process,), daemon=True)
        self._worker_reader_thread = reader
        reader.start()
        if not self._worker_atexit_registered:
            atexit.register(self._shutdown_worker)
            self._worker_atexit_registered = True
        self._drain_worker_queue()
        pong = self._worker_request_locked(
            {"cmd": "ping"},
            timeout_seconds=min(30, self.startup_timeout_seconds),
        )
        if not bool(pong.get("ok")):
            error = str(pong.get("error") or "worker_start_failed")
            self._shutdown_worker_locked()
            raise RuntimeError(f"AirLLM worker handshake failed: {error}")

    def _worker_request_locked(self, payload: Dict[str, Any], *, timeout_seconds: int) -> Dict[str, Any]:
        process = self._worker_process
        local_queue = self._worker_queue
        if process is None or process.stdin is None or local_queue is None:
            raise RuntimeError("AirLLM worker is not started.")

        request_id = uuid.uuid4().hex
        data = dict(payload or {})
        data["id"] = request_id
        process.stdin.write(json.dumps(data, ensure_ascii=True) + "\n")
        process.stdin.flush()

        deadline = time.monotonic() + max(1, int(timeout_seconds))
        while True:
            now = time.monotonic()
            if now >= deadline:
                tail = self._worker_error_tail()
                self._shutdown_worker_locked()
                detail = "AirLLM worker request timed out."
                if tail:
                    detail = f"{detail} logs: {tail}"
                raise RuntimeError(detail)

            if process.poll() is not None and local_queue.empty():
                tail = self._worker_error_tail()
                self._shutdown_worker_locked()
                detail = f"AirLLM worker exited with code {process.returncode}."
                if tail:
                    detail = f"{detail} logs: {tail}"
                raise RuntimeError(detail)

            wait_seconds = min(0.25, max(0.01, deadline - now))
            try:
                raw_item = local_queue.get(timeout=wait_seconds)
            except queue.Empty:
                continue

            if raw_item == self._WORKER_EOF_SENTINEL:
                tail = self._worker_error_tail()
                detail = "AirLLM worker stream closed unexpectedly."
                if tail:
                    detail = f"{detail} logs: {tail}"
                self._shutdown_worker_locked()
                raise RuntimeError(detail)

            try:
                response = json.loads(str(raw_item))
            except Exception:
                self._worker_log_tail.append(str(raw_item))
                continue

            if str(response.get("id") or "") != request_id:
                continue
            return response

    def _generate_via_worker(self, prompt: str, system_prompt: Optional[str]) -> str:
        attempts: List[str] = []
        for _attempt in range(2):
            try:
                with self._worker_lock:
                    self._ensure_worker_started_locked()
                    result = self._worker_request_locked(
                        {
                            "cmd": "generate",
                            "prompt": str(prompt or ""),
                            "system_prompt": str(system_prompt or ""),
                        },
                        timeout_seconds=self.request_timeout_seconds,
                    )
                if not bool(result.get("ok")):
                    raise RuntimeError(str(result.get("error") or "worker_generation_failed"))
                return str(result.get("text") or "").strip()
            except Exception as exc:
                attempts.append(str(exc))
                with self._worker_lock:
                    self._shutdown_worker_locked()
        raise RuntimeError("AirLLM worker generation failed: " + " | ".join(attempts[-2:]))

    @staticmethod
    def _path_free_gb(path: Path) -> float:
        try:
            usage = shutil.disk_usage(str(path))
            return float(usage.free) / float(1024**3)
        except Exception:
            return 0.0

    def _select_cache_dir(self, min_free_gb: float = 120.0) -> Optional[Path]:
        target = self.cache_dir
        if target is None:
            target = Path.home() / ".chintu" / "airllm_cache"

        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            return self.cache_dir

        if os.name != "nt":
            self.cache_dir = target
            return target

        target_free = self._path_free_gb(target)
        if target_free >= float(min_free_gb):
            self.cache_dir = target
            return target

        best_dir = target
        best_free = target_free
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if not root.exists():
                continue
            free_gb = self._path_free_gb(root)
            if free_gb <= best_free:
                continue
            candidate = root / "chintu_airllm_cache"
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
            best_dir = candidate
            best_free = free_gb

        if best_dir != target:
            logger.warning(
                "AirLLM cache path switched from %s (%.1fGB free) to %s (%.1fGB free)",
                target,
                target_free,
                best_dir,
                best_free,
            )
        self.cache_dir = best_dir
        return best_dir

    @staticmethod
    def _safe_model_key(model_id: str) -> str:
        key = str(model_id or "").strip().replace("/", "--").replace("\\", "--")
        return key.replace(":", "-")

    def _prepare_layer_shards_dir(self) -> Optional[Path]:
        if not self.cache_dir:
            return None
        shards_root = self.cache_dir / "layer_shards" / self._safe_model_key(self.model)
        ready_marker = shards_root / ".ready"
        if shards_root.exists() and not ready_marker.exists():
            quarantine_root = self.cache_dir / "verify_layer_shards"
            quarantine_root.mkdir(parents=True, exist_ok=True)
            quarantine_name = f"{shards_root.name}.partial_{int(time.time())}"
            quarantine_dir = quarantine_root / quarantine_name
            try:
                shards_root.replace(quarantine_dir)
                logger.warning(
                    "AirLLM detected incomplete layer shards at %s; moved to %s",
                    shards_root,
                    quarantine_dir,
                )
            except Exception as exc:
                logger.warning("AirLLM failed to quarantine incomplete layer shards %s: %s", shards_root, exc)
        shards_root.mkdir(parents=True, exist_ok=True)
        return shards_root

    @staticmethod
    def _mark_layer_shards_ready(layer_shards_dir: Optional[Path]) -> None:
        if not layer_shards_dir:
            return
        try:
            marker = layer_shards_dir / ".ready"
            marker.write_text("ok\n", encoding="utf-8")
        except Exception:
            return

    @staticmethod
    def _qwen3_layer_pairs_from_snapshot(snapshot_path: Path) -> List[tuple[str, str]]:
        index_path = snapshot_path / "model.safetensors.index.json"
        if not index_path.exists():
            return []
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            weight_map = payload.get("weight_map", {}) if isinstance(payload, dict) else {}
            if not isinstance(weight_map, dict):
                return []
            prefix = "model.language_model.layers."
            layer_ids = set()
            for key in weight_map.keys():
                if not isinstance(key, str) or not key.startswith(prefix):
                    continue
                rest = key[len(prefix) :]
                idx_raw = rest.split(".", 1)[0]
                if idx_raw.isdigit():
                    layer_ids.add(int(idx_raw))
            if not layer_ids:
                return []
            sorted_layer_ids = sorted(layer_ids)
            layer_pairs: List[tuple[str, str]] = [
                ("model.language_model.embed_tokens.", "model.language_model.embed_tokens."),
            ]
            layer_pairs.extend(
                [
                    (
                        f"model.language_model.layers.{idx}.",
                        f"model.language_model.layers.{idx}.",
                    )
                    for idx in sorted_layer_ids
                ]
            )
            layer_pairs.extend(
                [
                    ("model.language_model.norm.", "model.language_model.norm."),
                    ("lm_head.", "lm_head."),
                ]
            )
            return layer_pairs
        except Exception:
            return []

    @staticmethod
    def _airllm_split_dir(layer_shards_dir: Path, compression_mode: Optional[str]) -> Path:
        suffix = f"splitted_model.{compression_mode}" if compression_mode else "splitted_model"
        return layer_shards_dir / suffix

    @staticmethod
    def _is_split_complete(split_dir: Path, layer_names: List[str]) -> bool:
        if not split_dir.exists():
            return False
        for layer in layer_names:
            model_file = split_dir / f"{layer}safetensors"
            marker = split_dir / f"{layer}safetensors.done"
            if not model_file.exists() or not marker.exists():
                return False
        return True

    def _presplit_qwen3_layers(
        self,
        *,
        snapshot_path: Path,
        layer_shards_dir: Optional[Path],
        compression_mode: Optional[str],
    ) -> None:
        if layer_shards_dir is None or compression_mode is not None:
            return
        layer_pairs = self._qwen3_layer_pairs_from_snapshot(snapshot_path)
        if not layer_pairs:
            return
        target_layers = [target for _, target in layer_pairs]

        split_dir = self._airllm_split_dir(layer_shards_dir, compression_mode)
        if self._is_split_complete(split_dir, target_layers):
            return

        try:
            from safetensors.torch import load_file, save_file
        except Exception as exc:
            raise RuntimeError(f"safetensors is required for AirLLM pre-splitting: {exc}") from exc

        index_path = snapshot_path / "model.safetensors.index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        weight_map = payload.get("weight_map", {}) if isinstance(payload, dict) else {}
        if not isinstance(weight_map, dict):
            return

        source_files = sorted(
            {
                str(value)
                for value in weight_map.values()
                if isinstance(value, str) and value.endswith(".safetensors")
            }
        )
        if not source_files:
            return

        split_dir.mkdir(parents=True, exist_ok=True)
        completed = {
            layer
            for layer in target_layers
            if (split_dir / f"{layer}safetensors").exists()
            and (split_dir / f"{layer}safetensors.done").exists()
        }
        logger.info(
            "AirLLM pre-splitting %s layers for %s into %s",
            len(target_layers),
            self.model,
            split_dir,
        )

        for filename in source_files:
            if len(completed) >= len(target_layers):
                break
            shard_path = snapshot_path / filename
            if not shard_path.exists():
                continue
            state = load_file(str(shard_path), device="cpu")
            for source_layer, target_layer in layer_pairs:
                if target_layer in completed:
                    continue
                layer_state = {
                    (target_layer + key[len(source_layer) :]): value
                    for key, value in state.items()
                    if key.startswith(source_layer)
                }
                if not layer_state:
                    continue
                model_file = split_dir / f"{target_layer}safetensors"
                marker = split_dir / f"{target_layer}safetensors.done"
                save_file(layer_state, str(model_file))
                marker.touch(exist_ok=True)
                completed.add(target_layer)
            del state
            gc.collect()

        missing = [layer for layer in target_layers if layer not in completed]
        if missing:
            preview = ", ".join(missing[:4])
            raise RuntimeError(
                f"AirLLM pre-splitting incomplete for {self.model} ({len(missing)} layer files missing: {preview})."
            )

    def _resolve_model_source(self, hf_token: str) -> str:
        """Resolve model source path/id for AirLLM loading.

        For Qwen3/Qwen3.5 classes, pre-download full safetensor shards to avoid
        per-shard fetch incompatibilities in newer huggingface_hub versions.
        """
        model_source = self.model
        try:
            if Path(self.model).exists():
                return str(Path(self.model).resolve())
        except Exception:
            pass
        try:
            from transformers import AutoConfig

            if hf_token:
                config = AutoConfig.from_pretrained(self.model, trust_remote_code=True, token=hf_token)
            else:
                config = AutoConfig.from_pretrained(self.model, trust_remote_code=True)
            architectures = list(getattr(config, "architectures", []) or [])
            arch = str(architectures[0] if architectures else "").lower()
        except Exception:
            return model_source

        if "qwen3" not in arch:
            return model_source

        try:
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            snapshot_path = self._latest_snapshot_dir(self.model)
            if snapshot_path is None:
                if not self.allow_download:
                    raise RuntimeError(
                        "AirLLM local cache is missing for this model and auto-download is disabled. "
                        "Run scripts/chintu_airllm_prepare_model.py first or set CHINTU_AIRLLM_ALLOW_DOWNLOAD=true."
                    )
                hub = importlib.import_module("huggingface_hub")
                snapshot_download = getattr(hub, "snapshot_download", None)
                if not callable(snapshot_download):
                    raise RuntimeError("huggingface_hub.snapshot_download is unavailable.")
                kwargs: Dict[str, Any] = {
                    "allow_patterns": [
                        "*.json",
                        "tokenizer*",
                        "*.model",
                        "*.txt",
                        "*.py",
                    ],
                    "resume_download": True,
                }
                if hf_token:
                    kwargs["token"] = hf_token
                created = snapshot_download(self.model, **kwargs)
                snapshot_path = Path(created)

            missing = self._missing_weight_files(snapshot_path)
            if missing:
                if not self.allow_download:
                    preview = ", ".join(missing[:4])
                    raise RuntimeError(
                        f"AirLLM local model is incomplete ({len(missing)} missing shard(s): {preview}). "
                        "Run scripts/chintu_airllm_prepare_model.py to fetch remaining shards."
                    )
                self._download_missing_weights(
                    model_id=self.model,
                    missing_files=missing,
                    hf_token=hf_token,
                )
                missing = self._missing_weight_files(snapshot_path)
                if missing:
                    raise RuntimeError(
                        f"AirLLM model still incomplete after download ({len(missing)} missing shard(s))."
                    )

            self._ensure_legacy_shard_aliases(Path(snapshot_path))
            return str(snapshot_path)
        except Exception as exc:
            if self.allow_download:
                logger.warning("Qwen3 snapshot prepare failed, falling back to repo id: %s", exc)
                return model_source
            raise

    @staticmethod
    def _ensure_legacy_shard_aliases(snapshot_path: Path) -> None:
        """Create legacy shard aliases expected by AirLLM (model-00001-...).

        Newer Qwen repos use `model.safetensors-00001-...`. AirLLM currently
        builds old names. Hard links avoid duplicating disk usage.
        """
        index_path = snapshot_path / "model.safetensors.index.json"
        if not index_path.exists():
            return
        try:
            import json

            payload = json.loads(index_path.read_text(encoding="utf-8"))
            weight_map = payload.get("weight_map", {}) if isinstance(payload, dict) else {}
            unique_files = sorted({str(v) for v in weight_map.values() if isinstance(v, str)})
        except Exception:
            return
        for filename in unique_files:
            if not filename.startswith("model.safetensors-"):
                continue
            source = snapshot_path / filename
            if not source.exists():
                continue
            legacy_name = filename.replace("model.safetensors-", "model-", 1)
            legacy_path = snapshot_path / legacy_name
            if legacy_path.exists():
                continue
            try:
                os.link(source, legacy_path)
            except Exception:
                try:
                    shutil.copyfile(source, legacy_path)
                except Exception:
                    continue

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        if not self.model:
            self._available = False
            self._load_error = "CHINTU_AIRLLM_MODEL_ID is required when AirLLM is enabled."
            raise RuntimeError(self._load_error)

        with self._lock:
            if self._model is not None and self._tokenizer is not None:
                return
            self._install_optimum_bettertransformer_shim()
            try:
                airllm_mod = importlib.import_module("airllm")
            except Exception as exc:
                self._available = False
                self._load_error = (
                    "AirLLM dependency is not installed. "
                    "Install optional package with: pip install airllm. "
                    f"Import error: {exc}"
                )
                raise RuntimeError(self._load_error) from exc
            self._patch_airllm_qwen3_mapping()
            self._patch_airllm_snapshot_download()
            self._patch_airllm_clean_memory()

            auto_model = getattr(airllm_mod, "AutoModel", None) or getattr(airllm_mod, "AutoModelForCausalLM", None)
            if auto_model is None:
                self._available = False
                self._load_error = "AirLLM package does not expose AutoModel."
                raise RuntimeError(self._load_error)

            from_pretrained = getattr(auto_model, "from_pretrained", None)
            if not callable(from_pretrained):
                self._available = False
                self._load_error = "AirLLM AutoModel.from_pretrained is unavailable."
                raise RuntimeError(self._load_error)

            hf_token = (
                os.environ.get("HF_TOKEN")
                or os.environ.get("HUGGING_FACE_HUB_TOKEN")
                or os.environ.get("HUGGINGFACE_HUB_TOKEN")
                or ""
            )
            self._select_cache_dir()
            try:
                model_source = self._resolve_model_source(hf_token)
            except Exception as exc:
                self._available = False
                self._load_error = str(exc)
                raise RuntimeError(self._load_error) from exc
            if self.cache_dir:
                self.cache_dir.mkdir(parents=True, exist_ok=True)

            layer_shards_dir = self._prepare_layer_shards_dir()

            compression_mode = self._resolve_compression_mode()
            device_mode = self._resolve_device_mode()
            dtype_mode = self._resolve_dtype(resolved_device=device_mode)
            max_seq_len = self._resolve_max_seq_len()
            try:
                source_path = Path(str(model_source))
                if source_path.exists():
                    self._presplit_qwen3_layers(
                        snapshot_path=source_path,
                        layer_shards_dir=layer_shards_dir,
                        compression_mode=compression_mode,
                    )
            except Exception as exc:
                logger.warning("AirLLM pre-splitting step failed, falling back to AirLLM internal splitter: %s", exc)
            logger.info(
                "AirLLM loading model %s (compression=%s, device=%s, max_seq_len=%s, allow_download=%s, mode=%s)",
                self.model,
                compression_mode or "none",
                device_mode,
                max_seq_len,
                self.allow_download,
                self.runtime_mode,
            )
            base_kwargs: Dict[str, Any] = {
                "device": device_mode,
                "dtype": dtype_mode,
                "max_seq_len": max_seq_len,
                "layer_shards_saving_path": str(layer_shards_dir) if layer_shards_dir else None,
                "profiling_mode": False,
                "compression": compression_mode,
                "hf_token": hf_token or None,
                "delete_original": False,
            }
            kwargs_candidates: Iterable[Dict[str, Any]] = (
                {**base_kwargs, "prefetching": True},
                {**base_kwargs, "prefetching": False},
            )

            model = None
            errors: list[str] = []
            for candidate in kwargs_candidates:
                kwargs = {k: v for k, v in candidate.items() if v is not None}
                try:
                    model = from_pretrained(model_source, **kwargs)
                    break
                except TypeError as exc:
                    errors.append(str(exc))
                    try:
                        minimal_kwargs = {
                            "device": device_mode,
                            "compression": compression_mode,
                            "layer_shards_saving_path": str(layer_shards_dir) if layer_shards_dir else None,
                        }
                        minimal_kwargs = {k: v for k, v in minimal_kwargs.items() if v is not None}
                        model = from_pretrained(model_source, **minimal_kwargs)
                        break
                    except Exception as inner_exc:
                        errors.append(str(inner_exc))
                except Exception as exc:
                    errors.append(str(exc))
            if model is None:
                self._available = False
                detail = " | ".join(errors[:3])
                if "Not enough space" in detail:
                    detail = (
                        detail
                        + " Consider setting CHINTU_AIRLLM_CACHE_DIR to a drive with more free disk space."
                    )
                self._load_error = "Failed to load AirLLM model: " + detail
                raise RuntimeError(self._load_error)

            tokenizer = getattr(model, "tokenizer", None)
            if tokenizer is None:
                try:
                    transformers = importlib.import_module("transformers")
                    tokenizer = transformers.AutoTokenizer.from_pretrained(model_source, use_fast=True)
                except Exception as exc:
                    self._available = False
                    self._load_error = f"Failed to initialize tokenizer for AirLLM model: {exc}"
                    raise RuntimeError(self._load_error) from exc

            try:
                self._torch = importlib.import_module("torch")
            except Exception:
                self._torch = None

            self._model = model
            self._tokenizer = tokenizer
            self._available = True
            self._load_error = ""
            self._mark_layer_shards_ready(layer_shards_dir)
            logger.info("AirLLM client ready for model: %s", self.model)

    def _to_device(self, tensor: Any) -> Any:
        if tensor is None:
            return tensor
        torch_mod = self._torch
        if torch_mod is None:
            return tensor
        try:
            if hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available() and hasattr(tensor, "cuda"):
                return tensor.cuda()
        except Exception:
            return tensor
        return tensor

    def _decode_output(self, prompt_text: str, output: Any) -> str:
        sequence = output
        if hasattr(output, "sequences"):
            sequence = output.sequences
        if isinstance(sequence, (list, tuple)) and sequence:
            sequence = sequence[0]
        if hasattr(sequence, "__getitem__"):
            try:
                # Tensor with batch dimension.
                maybe = sequence[0]
                if maybe is not None and not isinstance(maybe, (int, float)):
                    sequence = maybe
            except Exception:
                pass
        decoded = self._tokenizer.decode(sequence, skip_special_tokens=True)
        if decoded.startswith(prompt_text):
            return decoded[len(prompt_text) :].strip()
        return decoded.strip()

    def _generate_inprocess(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        self._ensure_loaded()
        prompt_text = self._build_prompt(prompt, system_prompt)

        try:
            encoded = self._tokenizer(
                prompt_text,
                return_tensors="pt",
                truncation=True,
            )
            input_ids = self._to_device(encoded.get("input_ids"))
            attention_mask = self._to_device(encoded.get("attention_mask"))
            if input_ids is None:
                raise RuntimeError("Tokenizer did not return input_ids.")

            gen_kwargs = {
                "max_new_tokens": int(self.max_tokens),
                "use_cache": True,
            }
            if self.temperature > 0:
                gen_kwargs["temperature"] = float(self.temperature)
                gen_kwargs["do_sample"] = True

            errors: list[str] = []
            output = None
            try:
                output = self._model.generate(input_ids=input_ids, attention_mask=attention_mask, **gen_kwargs)
            except TypeError as exc:
                errors.append(str(exc))
            except Exception as exc:
                errors.append(str(exc))

            if output is None:
                try:
                    output = self._model.generate(input_ids, **gen_kwargs)
                except Exception as exc:
                    errors.append(str(exc))

            if output is None:
                raise RuntimeError("AirLLM generate failed: " + " | ".join(errors[:3]))
            return self._decode_output(prompt_text, output)
        except Exception as exc:
            raise RuntimeError(f"AirLLM generation failed: {exc}") from exc

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if self._use_subprocess_mode():
            return self._generate_via_worker(prompt, system_prompt)
        return self._generate_inprocess(prompt, system_prompt)

    def __del__(self) -> None:  # pragma: no cover - destructor timing is non-deterministic
        try:
            self._shutdown_worker()
        except Exception:
            pass

    def generate_stream(self, prompt: str, system_prompt: Optional[str] = None):
        text = self.generate(prompt, system_prompt)
        if not text:
            return
        words = text.split()
        if not words:
            yield text
            return
        for index, word in enumerate(words):
            suffix = " " if index < (len(words) - 1) else ""
            yield word + suffix

    def generate_content(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        return self.generate(prompt, system_instruction)

    def chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return self.generate(prompt, system_prompt)

    def chat_stream(self, prompt: str, system_prompt: Optional[str] = None):
        for chunk in self.generate_stream(prompt, system_prompt):
            yield chunk
