"""Ollama client for local LLM integration.

Implementation note:
- We call the Ollama HTTP API directly.
- This avoids relying on the `ollama` Python package (which can have dependency
  conflicts) while still supporting the same features Chintu needs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for a local Ollama server."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        num_threads: int | None = None,
        num_ctx: int | None = None,
        num_gpu: int = -1,
        keep_alive: int | None = None,
        think: bool | None = None,
    ):
        self._host = str(host or "http://localhost:11434").rstrip("/")
        self.model = str(model or "").strip() or "llama3.1:8b"
        self.max_tokens = int(max_tokens or 2048)
        self.temperature = float(temperature)
        self.num_threads = num_threads
        self.num_ctx = num_ctx
        self.num_gpu = int(num_gpu)
        self.keep_alive = keep_alive
        if self.keep_alive is None:
            raw_keep_alive = os.environ.get("CHINTU_OLLAMA_KEEP_ALIVE_SECONDS")
            if raw_keep_alive is not None:
                try:
                    self.keep_alive = int(str(raw_keep_alive).strip())
                except Exception:
                    self.keep_alive = None

        self.think = think
        if self.think is None:
            raw_think = os.environ.get("CHINTU_OLLAMA_THINK")
            if raw_think is not None:
                raw = str(raw_think).strip().lower()
                if raw in {"1", "true", "yes", "y", "on"}:
                    self.think = True
                elif raw in {"0", "false", "no", "n", "off"}:
                    self.think = False
            if self.think is None:
                # Default: disable verbose "thinking" token output to reduce latency/cost.
                self.think = False

        # Conservative default to avoid spiking CPU utilization.
        if self.num_threads is None:
            try:
                self.num_threads = min(int(os.cpu_count() or 4), 4)
            except Exception:
                self.num_threads = 4

        self._available = True
        self._unavailable_until = 0.0
        try:
            self._retry_after_seconds = float(str(os.environ.get("CHINTU_OLLAMA_RETRY_AFTER_SECONDS") or "8").strip())
        except Exception:
            self._retry_after_seconds = 8.0

    @property
    def host(self) -> str:
        return self._host

    @property
    def is_available(self) -> bool:
        """Whether Ollama is considered available.

        This is best-effort and flips to False after connection failures.
        """

        return bool(self._available)

    def _options(self) -> dict:
        options: dict = {
            "num_predict": self.max_tokens,
            "temperature": self.temperature,
        }
        if self.num_threads:
            options["num_thread"] = int(self.num_threads)
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        # If num_gpu is negative, let Ollama auto-select.
        if self.num_gpu >= 0:
            options["num_gpu"] = int(self.num_gpu)
        return options

    def prewarm(
        self,
        *,
        model: str | None = None,
        keep_alive: int | None = None,
        timeout_s: float = 45.0,
    ) -> bool:
        """Best-effort warm-up call to reduce cold-start latency.

        Uses a tiny `num_predict` and disables verbose thinking output. Safe to
        run in a background thread; failures are non-fatal.
        """

        model_name = str(model or self.model or "").strip() or self.model
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "options": {"num_predict": 1, "temperature": 0.0},
            "think": False,
        }
        if keep_alive is None:
            keep_alive = self.keep_alive
        if keep_alive is not None:
            payload["keep_alive"] = int(keep_alive)

        try:
            resp = requests.post(f"{self._host}/api/chat", json=payload, timeout=float(timeout_s))
            if resp.status_code != 200:
                return False
            data = resp.json() if resp.content else {}
            if isinstance(data, dict) and str(data.get("error") or "").strip():
                return False
            return True
        except Exception:
            return False

    def _can_attempt(self) -> bool:
        if self._available:
            return True
        try:
            return time.monotonic() >= float(self._unavailable_until or 0.0)
        except Exception:
            return True

    def check_model(self) -> bool:
        """Check if the configured model exists in Ollama."""

        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=3)
            if resp.status_code != 200:
                return False
            payload = resp.json() if resp.content else {}
            models = payload.get("models", []) if isinstance(payload, dict) else []
            names = []
            for entry in models:
                if isinstance(entry, dict) and entry.get("name"):
                    names.append(str(entry["name"]))
            if not names:
                return False
            base_names = {n.split(":")[0] for n in names}
            return self.model in base_names or self.model in names or f"{self.model}:latest" in names
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to check Ollama model: %s", exc)
            return False

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate a response via `/api/chat`."""

        if not self._can_attempt():
            return "[LLM not available - please install and run Ollama]"

        # If we previously failed, allow a retry after cooldown.
        self._available = True

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": str(prompt or "")})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(),
        }
        if self.keep_alive is not None:
            payload["keep_alive"] = int(self.keep_alive)
        if self.think is not None:
            payload["think"] = bool(self.think)

        try:
            resp = requests.post(f"{self._host}/api/chat", json=payload, timeout=90)
            if resp.status_code != 200:
                return f"[Error generating response: HTTP {resp.status_code}: {resp.text[:200]}]"
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                return "[Error generating response: invalid JSON payload]"
            msg = data.get("message")
            if isinstance(msg, dict):
                return str(msg.get("content") or "")
            # Fallback for older response shapes.
            return str(data.get("response") or "")
        except Exception as exc:  # noqa: BLE001
            self._available = False
            try:
                self._unavailable_until = time.monotonic() + float(self._retry_after_seconds or 0.0)
            except Exception:
                self._unavailable_until = 0.0
            logger.error("LLM generation error: %s", exc)
            return f"[Error generating response: {exc}]"

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Async wrapper around `generate()` (runs in a thread)."""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate, prompt, system_prompt)

    def generate_stream(self, prompt: str, system_prompt: Optional[str] = None):
        """Stream tokens via `/api/chat` line-delimited JSON."""

        if not self._can_attempt():
            yield "[LLM not available - please install and run Ollama]"
            return

        # If we previously failed, allow a retry after cooldown.
        self._available = True

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": str(prompt or "")})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": self._options(),
        }
        if self.keep_alive is not None:
            payload["keep_alive"] = int(self.keep_alive)
        if self.think is not None:
            payload["think"] = bool(self.think)

        try:
            resp = requests.post(f"{self._host}/api/chat", json=payload, stream=True, timeout=90)
            if resp.status_code != 200:
                yield f"[Error streaming response: HTTP {resp.status_code}]"
                return

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue

                msg = obj.get("message")
                if isinstance(msg, dict) and msg.get("content"):
                    yield str(msg.get("content"))
                elif obj.get("response"):
                    yield str(obj.get("response"))

                if obj.get("done") is True:
                    break

        except Exception as exc:  # noqa: BLE001
            self._available = False
            try:
                self._unavailable_until = time.monotonic() + float(self._retry_after_seconds or 0.0)
            except Exception:
                self._unavailable_until = 0.0
            logger.error("LLM streaming error: %s", exc)
            yield f"[Error: {exc}]"

    def draft_resume(self, role: str, experience_years: int = 5, skills: Optional[list] = None) -> str:
        """Generate a professional resume."""

        skills_str = ", ".join(skills) if skills else "relevant skills"
        prompt = (
            f"Draft a professional resume for a {role} with {experience_years} years of experience.\n"
            f"Include sections for: Summary, Experience, Skills ({skills_str}), Education.\n"
            "Make it concise but impactful. Use bullet points for achievements."
        )

        system = "You are a professional resume writer. Create ATS-friendly, achievement-focused resumes."
        return self.generate(prompt, system)

    def draft_sop(self, program: str, university: Optional[str] = None) -> str:
        """Generate a statement of purpose."""

        uni_str = f" at {university}" if university else ""
        prompt = (
            f"Write a compelling Statement of Purpose for applying to a {program} program{uni_str}.\n"
            "Include: academic background, motivation, relevant experience, future goals.\n"
            "Keep it personal and authentic. About 500-600 words."
        )

        system = "You are an expert in graduate school applications. Write compelling, genuine statements."
        return self.generate(prompt, system)

    def draft_email(self, purpose: str, recipient: Optional[str] = None) -> str:
        """Generate a professional email."""

        to_str = f" to {recipient}" if recipient else ""
        prompt = (
            f"Write a professional email{to_str} for the following purpose: {purpose}\n"
            "Keep it concise, polite, and professional."
        )

        system = "You are a professional communication expert. Write clear, effective emails."
        return self.generate(prompt, system)

    def answer_question(self, question: str) -> str:
        """Answer a general question."""

        system = "You are Chintu, a helpful personal AI assistant. Be concise but thorough."
        return self.generate(question, system)

    def generate_content(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Alias for generate() used by Thinking Mode."""

        return self.generate(prompt, system_instruction)

    def chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Alias for generate() used by Swarm agents."""

        return self.generate(prompt, system_prompt)
