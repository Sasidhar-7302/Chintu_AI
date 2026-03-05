"""Cloud model client implementations used by the router."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _update_provider_hints(provider: str, headers: Dict[str, str], usage: Dict[str, Any]) -> None:
    if not provider:
        return
    try:
        from chintu_backend.policy.budget_manager import get_budget_manager
    except Exception:
        return
    hints: Dict[str, str] = {}
    if isinstance(headers, dict):
        for key in (
            "x-ratelimit-limit-requests",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-reset-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-tokens",
        ):
            if key in headers:
                hints[key] = headers.get(key)
    if isinstance(usage, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            if key in usage:
                hints[f"usage_{key}"] = usage.get(key)
    if hints:
        get_budget_manager().update_provider_hints(provider, hints)


class GroqClient:
    """Fast cloud LLM client using Groq API (~100ms responses)."""

    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1"
        self._available = True
        self.last_headers: Dict[str, str] = {}
        self.last_usage: Dict[str, Any] = {}

        try:
            import httpx

            self._client = httpx.Client(timeout=30.0)
            logger.info("Groq client initialized with model: %s", model)
        except ImportError:
            logger.warning("httpx not available, Groq client disabled")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and bool(self.api_key)

    def chat(self, prompt: str, system_prompt: str = None, history: list = None) -> str:
        """Send chat request to Groq - typically ~100-500ms response."""
        if not self.is_available:
            raise RuntimeError("Groq client not available")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            for turn in history:
                messages.append({"role": turn["role"], "content": turn["content"]})

        messages.append({"role": "user", "content": prompt})

        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            try:
                self.last_headers = dict(response.headers)
            except Exception:
                self.last_headers = {}
            data = response.json()
            self.last_usage = data.get("usage", {}) if isinstance(data, dict) else {}
            _update_provider_hints("groq", self.last_headers, self.last_usage)
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("Groq API error: %s", exc)
            raise

    def chat_stream(self, prompt: str, system_prompt: str = None, history: list = None):
        """Stream chat response from Groq."""
        if not self.is_available:
            raise RuntimeError("Groq client not available")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            for turn in history:
                messages.append({"role": turn["role"], "content": turn["content"]})

        messages.append({"role": "user", "content": prompt})

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as response:
                try:
                    self.last_headers = dict(response.headers)
                except Exception:
                    self.last_headers = {}
                _update_provider_hints("groq", self.last_headers, {})
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            import json

                            data = json.loads(data_str)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except Exception:
                            pass
        except Exception as exc:
            logger.error("Groq streaming error: %s", exc)
            raise


class GeminiClient:
    """Google Gemini API client for vision, research, and long-context tasks."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._available = True
        self.last_headers: Dict[str, str] = {}
        self.last_usage: Dict[str, Any] = {}

        try:
            import httpx

            self._client = httpx.Client(timeout=60.0)
            logger.info("Gemini client initialized with model: %s", model)
        except ImportError:
            logger.warning("httpx not available, Gemini client disabled")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and bool(self.api_key)

    def chat(self, prompt: str, system_prompt: str = None) -> str:
        if not self.is_available:
            raise RuntimeError("Gemini client not available")

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System: {system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.post(
                f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": contents},
            )
            response.raise_for_status()
            try:
                self.last_headers = dict(response.headers)
            except Exception:
                self.last_headers = {}
            data = response.json()
            self.last_usage = data.get("usageMetadata", {}) if isinstance(data, dict) else {}
            _update_provider_hints("gemini", self.last_headers, self.last_usage)
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            raise

    def chat_stream(self, prompt: str, system_prompt: str = None):
        if not self.is_available:
            raise RuntimeError("Gemini client not available")

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System: {system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": contents},
            ) as response:
                try:
                    self.last_headers = dict(response.headers)
                except Exception:
                    self.last_headers = {}
                _update_provider_hints("gemini", self.last_headers, {})
                import json

                for line in response.iter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if "candidates" in data:
                                parts = data["candidates"][0].get("content", {}).get("parts", [])
                                for part in parts:
                                    if "text" in part:
                                        yield part["text"]
                        except Exception:
                            pass
        except Exception as exc:
            logger.error("Gemini streaming error: %s", exc)
            raise


class DeepSeekClient:
    """DeepSeek API client (OpenAI-compatible endpoint)."""

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.deepseek.com/v1"
        self._available = True
        self.last_headers: Dict[str, str] = {}
        self.last_usage: Dict[str, Any] = {}

        try:
            import httpx

            self._client = httpx.Client(timeout=60.0)
            logger.info("DeepSeek client initialized with model: %s", model)
        except ImportError:
            logger.warning("httpx not available, DeepSeek client disabled")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and bool(self.api_key)

    def chat(self, prompt: str, system_prompt: str = None) -> str:
        if not self.is_available:
            raise RuntimeError("DeepSeek client not available")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            try:
                self.last_headers = dict(response.headers)
            except Exception:
                self.last_headers = {}
            data = response.json()
            self.last_usage = data.get("usage", {}) if isinstance(data, dict) else {}
            _update_provider_hints("deepseek", self.last_headers, self.last_usage)
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("DeepSeek API error: %s", exc)
            raise

    def chat_stream(self, prompt: str, system_prompt: str = None):
        if not self.is_available:
            raise RuntimeError("DeepSeek client not available")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as response:
                try:
                    self.last_headers = dict(response.headers)
                except Exception:
                    self.last_headers = {}
                _update_provider_hints("deepseek", self.last_headers, {})
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            import json

                            data = json.loads(data_str)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except Exception:
                            pass
        except Exception as exc:
            logger.error("DeepSeek streaming error: %s", exc)
            raise


class NvidiaClient:
    """NVIDIA NIM API client (OpenAI-compatible endpoint)."""

    def __init__(self, api_key: str, model: str = "moonshotai/kimi-k2.5", base_url: str = "https://integrate.api.nvidia.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._available = True
        self.last_headers: Dict[str, str] = {}
        self.last_usage: Dict[str, Any] = {}

        try:
            import httpx

            self._client = httpx.Client(timeout=60.0)
            logger.info("NVIDIA client initialized with model: %s", model)
        except ImportError:
            logger.warning("httpx not available, NVIDIA client disabled")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and bool(self.api_key)

    def chat(self, prompt: str, system_prompt: str = None) -> str:
        if not self.is_available:
            raise RuntimeError("NVIDIA client not available")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            try:
                self.last_headers = dict(response.headers)
            except Exception:
                self.last_headers = {}
            data = response.json()
            self.last_usage = data.get("usage", {}) if isinstance(data, dict) else {}
            _update_provider_hints("nvidia", self.last_headers, self.last_usage)
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("NVIDIA API error: %s", exc)
            raise

    def generate(self, prompt: str, system_prompt: str = None) -> str:
        return self.chat(prompt, system_prompt=system_prompt)

    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        return self.chat(prompt, system_prompt=system_instruction)

    def chat_stream(self, prompt: str, system_prompt: str = None):
        if not self.is_available:
            raise RuntimeError("NVIDIA client not available")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as response:
                try:
                    self.last_headers = dict(response.headers)
                except Exception:
                    self.last_headers = {}
                _update_provider_hints("nvidia", self.last_headers, {})
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            import json

                            data = json.loads(data_str)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except Exception:
                            pass
        except Exception as exc:
            logger.error("NVIDIA streaming error: %s", exc)
            raise
