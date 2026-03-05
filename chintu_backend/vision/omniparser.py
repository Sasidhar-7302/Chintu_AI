"""OmniParser v2 - Vision-based Screen Understanding.

Supports cloud and local vision backends with local-first defaults:
1. Ollama (Qwen3-VL preferred) for private/local execution.
2. Google Gemini as cloud fallback when local is unavailable.

Enables commands like "what's on my screen" and "click the submit button".
"""

import os
import logging
import base64
import json
import io
import time
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

from chintu_backend.core.playbooks.vision import (
    ANALYZE_SCREEN_JSON_PROMPT,
    DESCRIBE_SCREEN_PROMPT,
)

# Try to import Google GenAI (New SDK)
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai not installed for vision")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def _ollama_reachable(host: str) -> bool:
    host = str(host or "").strip().rstrip("/")
    if not host:
        return False
    try:
        resp = requests.get(f"{host}/api/tags", timeout=1.5)
        return bool(resp.status_code == 200)
    except Exception:
        return False


def _list_ollama_models(host: str) -> List[Dict[str, Any]]:
    host = str(host or "").strip().rstrip("/")
    if not host:
        return []
    try:
        resp = requests.get(f"{host}/api/tags", timeout=2.0)
        if resp.status_code != 200:
            return []
        payload = resp.json() if resp.content else {}
        models = payload.get("models")
        if isinstance(models, list):
            return [m for m in models if isinstance(m, dict)]
        return []
    except Exception:
        return []


def _looks_like_vision_model(name: str, details: Optional[Dict[str, Any]] = None) -> bool:
    """Heuristic detection of Ollama vision-capable models."""
    model_name = str(name or "").strip().lower()
    if not model_name:
        return False
    vision_tokens = (
        "qwen3-vl",
        "llava",
        "moondream",
        "moondream2",
        "vision",
        "vl",
        "qwen2.5-vl",
        "qwen2-vl",
        "llama3.2-vision",
        "mllama",
        "minicpm-v",
        "qwen2.5vl",
        "qwen-vl",
        "bakllava",
    )
    if any(tok in model_name for tok in vision_tokens):
        return True
    d = details or {}
    family = str((d.get("family") or "")).lower()
    families = [str(x).lower() for x in (d.get("families") or []) if x]
    bag = " ".join([family] + families)
    return any(tok in bag for tok in vision_tokens)


def _pick_ollama_vision_model(host: str, preferred: str = "") -> Optional[str]:
    models = _list_ollama_models(host)
    if not models:
        return None

    preferred_norm = str(preferred or "").strip().lower()
    if preferred_norm:
        for model in models:
            name = str(model.get("name") or model.get("model") or "").strip()
            if not name:
                continue
            normalized = name.lower()
            bare = normalized.split(":", 1)[0]
            if (
                normalized == preferred_norm
                or bare == preferred_norm
                or normalized.startswith(f"{preferred_norm}:")
            ):
                # Respect explicit preference even if heuristics don't detect vision capability.
                return name

    ranked_candidates: List[Tuple[int, str]] = []
    priority = [
        "qwen2.5-vl:7b",
        "llava:7b",
        "llama3.2-vision:11b",
        "qwen3-vl:4b",
        "qwen3-vl:2b",
        "qwen2.5-vl:3b",
        "qwen3-vl:8b",
        "moondream",
    ]
    for model in models:
        name = str(model.get("name") or model.get("model") or "").strip()
        if not name or not _looks_like_vision_model(name, model.get("details")):
            continue
        normalized = name.lower()
        score = 0
        for idx, preferred_name in enumerate(priority):
            preferred_norm = preferred_name.lower()
            preferred_base = preferred_norm.split(":", 1)[0]
            if normalized == preferred_norm:
                score = 1000 - idx
                break
            if normalized.startswith(f"{preferred_norm}:"):
                score = 900 - idx
                break
            if normalized == preferred_base or normalized.startswith(f"{preferred_base}:"):
                score = 700 - idx
                break
        ranked_candidates.append((score, name))

    if ranked_candidates:
        ranked_candidates.sort(key=lambda item: item[0], reverse=True)
        return ranked_candidates[0][1]
    return None


def _ordered_ollama_vision_models(host: str, preferred: str = "") -> List[str]:
    """Return installed vision-capable models in descending quality order."""
    models = _list_ollama_models(host)
    if not models:
        return []

    preferred_norm = str(preferred or "").strip().lower()
    preferred_installed = ""
    if preferred_norm:
        for model in models:
            name = str(model.get("name") or model.get("model") or "").strip()
            if not name:
                continue
            normalized = name.lower()
            bare = normalized.split(":", 1)[0]
            if (
                normalized == preferred_norm
                or bare == preferred_norm
                or normalized.startswith(f"{preferred_norm}:")
            ):
                preferred_installed = name
                break

    priority = [
        "qwen2.5-vl:7b",
        "llava:7b",
        "llama3.2-vision:11b",
        "qwen3-vl:4b",
        "qwen3-vl:2b",
        "qwen2.5-vl:3b",
        "qwen3-vl:8b",
        "moondream",
    ]

    scored: List[Tuple[int, str]] = []
    seen: set[str] = set()
    for model in models:
        name = str(model.get("name") or model.get("model") or "").strip()
        if not name:
            continue
        normalized = name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if not _looks_like_vision_model(name, model.get("details")):
            continue

        score = 0
        for idx, preferred_name in enumerate(priority):
            preferred_norm = preferred_name.lower()
            preferred_base = preferred_norm.split(":", 1)[0]
            if normalized == preferred_norm:
                score = 1000 - idx
                break
            if normalized.startswith(f"{preferred_norm}:"):
                score = 900 - idx
                break
            if normalized == preferred_base or normalized.startswith(f"{preferred_base}:"):
                score = 700 - idx
                break
        scored.append((score, name))

    if not scored:
        return []

    scored.sort(key=lambda item: item[0], reverse=True)
    ordered = [name for _, name in scored]

    if preferred_installed and preferred_installed not in ordered:
        ordered = [preferred_installed] + ordered
    elif preferred_norm:
        preferred_hits = [
            name
            for name in ordered
            if name.lower() == preferred_norm
            or name.lower().split(":", 1)[0] == preferred_norm
            or name.lower().startswith(f"{preferred_norm}:")
        ]
        if preferred_hits:
            preferred_name = preferred_hits[0]
            ordered = [preferred_name] + [name for name in ordered if name != preferred_name]
    return ordered


def _is_ollama_model_installed(host: str, model_name: str) -> bool:
    name = str(model_name or "").strip().lower()
    if not name:
        return False
    bare = name.split(":", 1)[0]
    for model in _list_ollama_models(host):
        candidate = str(model.get("name") or model.get("model") or "").strip().lower()
        if not candidate:
            continue
        candidate_bare = candidate.split(":", 1)[0]
        if candidate == name or candidate_bare == bare or candidate.startswith(f"{bare}:"):
            return True
    return False


def _is_retryable_ollama_error(text: str) -> bool:
    body = str(text or "").lower()
    retryable_tokens = (
        "model not found",
        "not found",
        "out of memory",
        "insufficient memory",
        "cuda out of memory",
        "failed to load model",
        "timed out",
        "timeout",
        "connection reset",
    )
    return any(token in body for token in retryable_tokens)


def _extract_openai_message_text(content: Any) -> str:
    """Normalize OpenAI-compatible message content to plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                txt = item.get("text")
                if txt:
                    parts.append(str(txt))
        return "\n".join(p for p in parts if p).strip()
    return ""


@dataclass
class UIElement:
    """Represents a detected UI element."""
    element_type: str  # button, text, input, image, link
    text: str
    location: str  # description like "top-left", "center"
    confidence: float
    bounds: Optional[Tuple[int, int, int, int]] = None  # x, y, width, height


class OmniParser:
    """Vision-based screen understanding using Gemini Vision API or Local Ollama."""
    
    def __init__(self, api_key: str = None):
        # 1. Try Configured API Keys
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_AI_KEY")
        
        # Also try chintu config
        if not self.api_key:
            try:
                from ..core.config import get_config
                self.api_key = get_config().google_ai_key
            except ImportError:
                pass
        
        self.client = None
        self._initialized = False
        self.use_ollama = False
        self.ollama_host = os.environ.get("CHINTU_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
        self.ollama_model = os.environ.get("CHINTU_VISION_OLLAMA_MODEL") or "llava:7b"
        self._missing_ollama_vision_logged = False
        self.prefer_local = _env_flag("CHINTU_VISION_PREFER_LOCAL", default=True)
        self._model_failure_backoff_until: Dict[str, float] = {}
        self._model_failure_counts: Dict[str, int] = {}

        # Also try chintu config for host overrides
        try:
            from ..core.config import get_config

            cfg = get_config()
            cfg_host = getattr(cfg, "ollama_host", None)
            if cfg_host:
                self.ollama_host = str(cfg_host)
        except Exception:
            pass
        
        # Determine Backend
        ollama_ready = _ollama_reachable(self.ollama_host)
        if self.prefer_local and ollama_ready:
            self._activate_ollama_backend()
            if (not self.ollama_model) and self.api_key and GEMINI_AVAILABLE:
                self.backend = "gemini"
                self.use_ollama = False
                logger.info("No local vision model detected; using Gemini backend until local model is available.")
        elif self.api_key and GEMINI_AVAILABLE:
            self.backend = "gemini"
        elif ollama_ready:
            self._activate_ollama_backend()
        else:
            self.backend = "none"
            logger.warning("No vision backend available (Missing API Key and/or Ollama server)")

        if self.backend == "none" and self.api_key and GEMINI_AVAILABLE:
            self.backend = "gemini"
            logger.info("OmniParser falling back to Gemini backend.")

    def _activate_ollama_backend(self) -> None:
        self.backend = "ollama"
        self.use_ollama = True
        selected = _pick_ollama_vision_model(self.ollama_host, self.ollama_model)
        if selected:
            self.ollama_model = selected
            self._missing_ollama_vision_logged = False
            logger.info("OmniParser using LOCAL backend (Ollama HTTP, model=%s)", self.ollama_model)
            return
        self.ollama_model = ""
        self._missing_ollama_vision_logged = True
        logger.warning(
            "Ollama is reachable but no vision model is installed. "
            "Install one with: ollama pull qwen2.5-vl:7b (or llava:7b)"
        )

    def _record_candidate_failure(self, candidate: str, retryable: bool) -> None:
        key = str(candidate or "").strip().lower()
        if not key:
            return
        count = int(self._model_failure_counts.get(key, 0)) + 1
        self._model_failure_counts[key] = count
        # Back off noisy/broken candidates to avoid repeating the same fallback loop.
        if retryable and count >= 2:
            self._model_failure_backoff_until[key] = time.monotonic() + 120.0

    def _clear_candidate_failure(self, candidate: str) -> None:
        key = str(candidate or "").strip().lower()
        if not key:
            return
        self._model_failure_counts.pop(key, None)
        self._model_failure_backoff_until.pop(key, None)

    def _ensure_initialized(self):
        """Initialize Gemini client if needed."""
        if self._initialized:
            return
            
        if self.backend == "gemini":
            try:
                self.client = genai.Client(api_key=self.api_key)
                self._initialized = True
                logger.info("OmniParser initialized with Gemini Vision")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client: {e}")
                # Fallback to Ollama if initialization fails
                if _ollama_reachable(self.ollama_host):
                    self.backend = "ollama"
                    self.use_ollama = True
                    logger.info("Falling back to Ollama")
        
        elif self.backend == "ollama":
            self._initialized = True

    def _generate(self, prompt: str, image_bytes: bytes, _ollama_retry: bool = False) -> Optional[str]:
        """Generate content using the active backend."""
        self._ensure_initialized()
        
        if self.backend == "gemini" and self.client:
            try:
                response = self.client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type="image/png")
                    ]
                )
                return response.text
            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                # If rate limited, fallback to Ollama?
                if "429" in str(e) and _ollama_reachable(self.ollama_host):
                     logger.warning("Gemini Rate Limit hit. Switching to Local Ollama.")
                     self.backend = "ollama"
                     self.use_ollama = True
                     selected = _pick_ollama_vision_model(self.ollama_host, self.ollama_model)
                     if selected:
                         self.ollama_model = selected
                     else:
                         self.ollama_model = ""
                     return self._generate(prompt, image_bytes) # Retry with ollama
                return None

        elif self.backend == "ollama":
            try:
                host = str(self.ollama_host or "http://localhost:11434").rstrip("/")
                model = str(self.ollama_model or "").strip()
                if not model:
                    selected = _pick_ollama_vision_model(host, "")
                    if selected:
                        model = selected
                        self.ollama_model = selected
                elif not _is_ollama_model_installed(host, model):
                    selected = _pick_ollama_vision_model(host, "")
                    if selected:
                        model = selected
                        self.ollama_model = selected
                    else:
                        self.ollama_model = ""
                if not model:
                    if not self._missing_ollama_vision_logged:
                        logger.warning(
                            "No Ollama vision model installed. Install one with: ollama pull qwen2.5-vl:7b"
                        )
                        self._missing_ollama_vision_logged = True
                    return None
                self._missing_ollama_vision_logged = False

                image_b64 = base64.b64encode(image_bytes).decode("ascii")
                candidates = _ordered_ollama_vision_models(host, model)
                if not candidates:
                    candidates = [model]
                now = time.monotonic()
                filtered = [
                    c for c in candidates
                    if now >= float(self._model_failure_backoff_until.get(str(c).lower(), 0.0))
                ]
                if filtered:
                    candidates = filtered

                last_error = ""
                for candidate in candidates:
                    payload = {
                        "model": candidate,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                                "images": [image_b64],
                            }
                        ],
                        "stream": False,
                    }

                    try:
                        resp = requests.post(f"{host}/api/chat", json=payload, timeout=90)
                    except Exception as req_err:
                        last_error = str(req_err)
                        self._record_candidate_failure(candidate, retryable=True)
                        logger.warning(
                            "Ollama vision model '%s' request failed (%s). Trying fallback.",
                            candidate,
                            last_error[:180],
                        )
                        continue
                    if resp.status_code != 200:
                        body = str(resp.text or "")[:200]
                        last_error = f"http {resp.status_code}: {body}"
                        if _is_retryable_ollama_error(body):
                            self._record_candidate_failure(candidate, retryable=True)
                            logger.warning(
                                "Ollama vision model '%s' failed (%s). Trying fallback.",
                                candidate,
                                last_error,
                            )
                            continue
                        self._record_candidate_failure(candidate, retryable=False)
                        logger.error("Ollama Vision HTTP %s: %s", resp.status_code, body)
                        continue

                    data = resp.json() if resp.content else {}
                    if isinstance(data, dict):
                        err = str(data.get("error") or "")
                        if err:
                            last_error = err
                            if _is_retryable_ollama_error(err):
                                self._record_candidate_failure(candidate, retryable=True)
                                logger.warning(
                                    "Ollama vision model '%s' returned retryable error: %s. Trying fallback.",
                                    candidate,
                                    err[:180],
                                )
                                continue
                            self._record_candidate_failure(candidate, retryable=False)
                            logger.error("Ollama vision model '%s' error: %s", candidate, err[:180])
                            continue

                    msg = data.get("message") if isinstance(data, dict) else None
                    content = None
                    if isinstance(msg, dict):
                        content = msg.get("content")
                    elif isinstance(data, dict) and data.get("response"):
                        content = str(data.get("response"))

                    if content:
                        self._clear_candidate_failure(candidate)
                        if candidate != self.ollama_model:
                            logger.warning(
                                "Ollama vision fallback selected model '%s' (previous '%s').",
                                candidate,
                                self.ollama_model,
                            )
                        self.ollama_model = candidate
                        return content

                if last_error:
                    logger.error("All Ollama vision candidates failed. Last error: %s", last_error[:200])
                return None
            except Exception as e:
                logger.error(f"Ollama Vision error: {e}")
                return None
                
        return None

    def analyze_screen(self, image_path: str = None, 
                       image_bytes: bytes = None) -> Dict[str, Any]:
        """Analyze a screenshot and return structured description."""
        
        # Load image
        if image_path:
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as e:
                return {"error": f"Failed to read image: {e}"}
        
        if not image_bytes:
            return {"error": "No image provided"}
            
        prompt = ANALYZE_SCREEN_JSON_PROMPT

        response_text = self._generate(prompt, image_bytes)
        if not response_text:
             return {
                "error": "Vision model failed",
                "description": "I cannot analyze the screen right now."
            }

        result = self._parse_response(response_text)
        result["raw_response"] = response_text
        return result
            
    def describe_screen(self, image_path: str = None,
                        image_bytes: bytes = None) -> str:
        """Get a natural language description suitable for voice."""
        
        if image_path:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        
        if not image_bytes:
            return "No screenshot available."
            
        prompt = DESCRIBE_SCREEN_PROMPT

        text = self._generate(prompt, image_bytes)
        if not text:
            return "I cannot see your screen right now. Vision is not available."
        return text.strip()
    
    def find_element(self, image_path: str, element_description: str) -> Dict[str, Any]:
        """Find a UI element matching the description."""
        
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except:
             return {"found": False, "error": "Image load failed"}

        prompt = f"""Look at this screenshot and find the visible UI element described as: "{element_description}"

Return a JSON object with this EXACT structure:

{{
  "found": true/false,
  "description": "brief description of what was found and its location",
  "coordinates": [x_percent, y_percent]  // Center point as percentage (0-100). Top-left is [0,0].
}}

If not found, set "found": false and "coordinates": null.
DO NOT output conversational text, ONLY the JSON."""

        text = self._generate(prompt, image_bytes)
        if not text:
            return {"found": False, "error": "API failed"}
            
        return self._parse_json_response(text)

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse strict JSON response."""
        try:
            clean = text.strip()
            # Try to find JSON block
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            
            # Find start and end braces if mixed with text
            start = clean.find("{")
            end = clean.rfind("}") + 1
            if start != -1 and end != -1:
                clean = clean[start:end]
                
            return json.loads(clean)
        except Exception:
            # Fallback logic for models that chatter
            lower = text.lower()
            return {
                "found": "found" in lower and "not found" not in lower,
                "description": text[:200],
                "coordinates": None # Cannot reliably guess without JSON
            }
    
    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract the first valid JSON object from model output."""
        raw = str(text or "").strip()
        if not raw:
            return None

        candidates: List[str] = []
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                candidate = part.strip()
                if not candidate:
                    continue
                if candidate.lower().startswith("json"):
                    candidate = candidate[4:].strip()
                if candidate.startswith("{") and candidate.endswith("}"):
                    candidates.append(candidate)

        # Balanced brace scan for inline JSON.
        starts = [idx for idx, ch in enumerate(raw) if ch == "{"]
        for start in starts:
            depth = 0
            for idx in range(start, len(raw)):
                ch = raw[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(raw[start : idx + 1])
                        break

        for candidate in candidates:
            try:
                obj = json.loads(candidate)
            except Exception:
                continue
            if isinstance(obj, dict):
                return obj
        return None

    @staticmethod
    def _element_type_from_text(text: str) -> str:
        t = str(text or "").lower()
        if any(k in t for k in ("button", "btn", "submit", "click")):
            return "button"
        if any(k in t for k in ("input", "search", "textbox", "field", "type here")):
            return "input"
        if any(k in t for k in ("menu", "dropdown", "tab", "sidebar", "toolbar")):
            return "menu"
        if any(k in t for k in ("link", "url", "http", "anchor")):
            return "link"
        if any(k in t for k in ("image", "logo", "icon", "thumbnail", "photo", "video")):
            return "image"
        return "text"

    @staticmethod
    def _location_from_text(text: str) -> str:
        t = str(text or "").lower()
        has_top = "top" in t
        has_bottom = "bottom" in t
        has_left = "left" in t
        has_right = "right" in t
        if has_top and has_left:
            return "top-left"
        if has_top and has_right:
            return "top-right"
        if has_bottom and has_left:
            return "bottom-left"
        if has_bottom and has_right:
            return "bottom-right"
        if has_top:
            return "top"
        if has_bottom:
            return "bottom"
        if has_left:
            return "left"
        if has_right:
            return "right"
        if "center" in t or "middle" in t:
            return "center"
        return "unknown"

    @staticmethod
    def _is_placeholder_value(value: str) -> bool:
        v = str(value or "").strip().lower()
        return v in {
            "",
            "n/a",
            "na",
            "none",
            "null",
            "unknown",
            "optional",
            "optional visible text",
            "placeholder",
            "string",
            "text",
        }

    def _coerce_analysis_dict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize various model JSON shapes into a stable schema."""
        description = str(
            payload.get("description")
            or payload.get("summary")
            or payload.get("screen_description")
            or payload.get("main_content")
            or ""
        ).strip()

        elements_raw = payload.get("elements") or payload.get("key_elements") or []
        if isinstance(elements_raw, dict):
            elements_raw = [elements_raw]
        if not isinstance(elements_raw, list):
            elements_raw = [elements_raw] if elements_raw else []

        elements: List[Dict[str, str]] = []
        for item in elements_raw:
            if isinstance(item, dict):
                name = str(
                    item.get("name")
                    or item.get("label")
                    or item.get("title")
                    or item.get("text")
                    or item.get("description")
                    or ""
                ).strip()
                if self._is_placeholder_value(name):
                    continue
                text_hint = str(item.get("text") or "").strip()
                if self._is_placeholder_value(text_hint):
                    text_hint = ""
                location = str(item.get("location") or "").strip() or self._location_from_text(name)
                element_type = str(item.get("type") or "").strip() or self._element_type_from_text(name)
            else:
                name = str(item).strip()
                if self._is_placeholder_value(name):
                    continue
                text_hint = ""
                location = self._location_from_text(name)
                element_type = self._element_type_from_text(name)
            elements.append(
                {
                    "name": name[:120],
                    "type": element_type[:40],
                    "location": location[:40],
                    "text": text_hint[:200],
                }
            )
            if len(elements) >= 8:
                break

        text_content = str(
            payload.get("text_content")
            or payload.get("readable_text")
            or payload.get("text")
            or payload.get("ocr")
            or ""
        ).strip()
        if self._is_placeholder_value(text_content):
            text_content = ""

        actions_raw = payload.get("actions") or payload.get("available_actions") or []
        if isinstance(actions_raw, str):
            actions_raw = [x.strip(" -") for x in actions_raw.split("\n") if x.strip()]
        if not isinstance(actions_raw, list):
            actions_raw = [str(actions_raw)] if actions_raw else []
        actions: List[str] = []
        for action in actions_raw:
            s = str(action).strip(" -")
            if s:
                actions.append(s[:160])
            if len(actions) >= 6:
                break

        if not description:
            if elements:
                names = ", ".join(e["name"] for e in elements[:3])
                description = f"I can see a screen with key elements such as {names}."
            elif text_content:
                description = "I can see your screen and extracted readable text."
            else:
                description = "I can see your screen, but details are limited."

        success = bool(payload.get("success", True))
        success = bool(success and (description or elements or text_content or actions))

        return {
            "success": success,
            "description": description,
            "elements": elements,
            "text_content": text_content[:1200],
            "actions": actions,
        }

    def _parse_plain_response(self, text: str) -> Dict[str, Any]:
        """Best-effort parsing for non-JSON model responses."""
        raw = str(text or "").strip()
        if not raw:
            return {
                "success": False,
                "description": "I can see your screen, but I could not parse details.",
                "elements": [],
                "text_content": "",
                "actions": [],
            }

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        sections: Dict[str, List[str]] = {"description": [], "elements": [], "text": [], "actions": []}
        current = "description"
        heading_map = {
            "description": "description",
            "overview": "description",
            "summary": "description",
            "key elements": "elements",
            "elements": "elements",
            "ui elements": "elements",
            "text content": "text",
            "readable text": "text",
            "ocr": "text",
            "actions available": "actions",
            "actions": "actions",
            "next actions": "actions",
        }

        for line in lines:
            normalized = line.lower().lstrip("# ").strip()
            switched = False
            for key, section in heading_map.items():
                if normalized.startswith(f"{key}:") or normalized == key:
                    current = section
                    remainder = line.split(":", 1)[1].strip() if ":" in line else ""
                    if remainder:
                        sections[current].append(remainder)
                    switched = True
                    break
            if switched:
                continue
            cleaned = line.lstrip("-*0123456789. ").strip()
            if cleaned:
                sections[current].append(cleaned)

        description = " ".join(sections["description"]).strip()
        if not description:
            description = lines[0]

        elements: List[Dict[str, str]] = []
        for entry in sections["elements"]:
            name = entry.strip(" -")
            if not name:
                continue
            elements.append(
                {
                    "name": name[:120],
                    "type": self._element_type_from_text(name)[:40],
                    "location": self._location_from_text(name)[:40],
                    "text": "",
                }
            )
            if len(elements) >= 8:
                break

        actions: List[str] = []
        for entry in sections["actions"]:
            action = entry.strip(" -")
            if action:
                actions.append(action[:160])
            if len(actions) >= 6:
                break

        text_content = " ".join(sections["text"]).strip()
        if not text_content:
            quoted = []
            for token in raw.split('"'):
                token = token.strip()
                if token and " " in token:
                    quoted.append(token)
            if quoted:
                text_content = " | ".join(quoted[:3])

        return {
            "success": True,
            "description": description[:600] if description else "I can see your screen.",
            "elements": elements,
            "text_content": text_content[:1200],
            "actions": actions,
        }

    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Parse response into structured format."""
        parsed = self._extract_json_object(text)
        if parsed:
            return self._coerce_analysis_dict(parsed)
        return self._parse_plain_response(text)

# Global instance
_parser: Optional[OmniParser] = None

def get_omniparser() -> OmniParser:
    """Get the global OmniParser instance."""
    global _parser
    if _parser is None:
        _parser = OmniParser()
    return _parser
