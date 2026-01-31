"""Ollama client for local LLM integration."""

import asyncio
from typing import Optional, AsyncGenerator, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Try to import ollama
try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    logger.warning("ollama package not installed")

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class OllamaClient:
    """
    Client for Ollama local LLM.
    Provides both sync and async interfaces.
    """
    
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:1.5b",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        num_threads: int = None,
        num_ctx: int = None,
        num_gpu: int = -1,
    ):
        self.host = host
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.num_threads = num_threads  # CPU threads (None = auto-detect)
        self.num_ctx = num_ctx  # Context window (None = use default)
        self.num_gpu = num_gpu  # GPU layers (-1 = CPU only)
        
        # Auto-detect CPU threads if not specified
        if self.num_threads is None:
            try:
                import os
                self.num_threads = min(os.cpu_count() or 4, 4)  # Cap at 4 for i5 8th gen
            except Exception:
                self.num_threads = 4
        
        self._available = False
        self._client = None
        
        if HAS_OLLAMA:
            try:
                self._client = ollama.Client(host=host)
                self._available = True
                logger.info(f"Ollama client initialized (host: {host}, model: {model})")
            except Exception as e:
                logger.warning(f"Failed to initialize Ollama client: {e}")
    
    @property
    def is_available(self) -> bool:
        """Check if Ollama is available."""
        return self._available
    
    def check_model(self) -> bool:
        """Check if the configured model is available."""
        if not self._available:
            return False
        
        try:
            models = self._client.list()
            entries = None
            if isinstance(models, dict):
                entries = models.get("models", [])
            else:
                entries = getattr(models, "models", []) or []

            names = []
            for entry in entries:
                if isinstance(entry, dict):
                    name = entry.get("name", "")
                else:
                    name = getattr(entry, "name", "") or getattr(entry, "model", "")
                if name:
                    names.append(name)

            model_names = [n.split(":")[0] for n in names]
            return self.model in model_names or f"{self.model}:latest" in names
        except Exception as e:
            logger.error(f"Failed to check model: {e}")
            return False
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate a response from the LLM.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            Generated text response
        """
        if not self._available:
            return "[LLM not available - please install and run Ollama]"
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # Build optimized options for CPU inference
            options = {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            }
            
            # Add GPU/CPU settings
            if self.num_threads:
                options["num_thread"] = self.num_threads
            if self.num_ctx:
                options["num_ctx"] = self.num_ctx
            
            # Use explicit num_gpu. If -1, let Ollama handle it (often defaults to GPU if available)
            # but we pass our config value which defaults to 50 for better reliability.
            if self.num_gpu >= 0:
                options["num_gpu"] = self.num_gpu
            # else: do not set num_gpu, let Ollama auto-detect
            
            response = self._client.chat(
                model=self.model,
                messages=messages,
                options=options,
            )
            
            return response.get("message", {}).get("content", "")
            
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            return f"[Error generating response: {e}]"
    
    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Async version of generate."""
        # Run sync method in executor
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate, prompt, system_prompt)
    
    def generate_stream(self, prompt: str, system_prompt: Optional[str] = None):
        """
        Stream generate response tokens.
        
        Yields:
            Text chunks as they are generated
        """
        if not self._available:
            yield "[LLM not available - please install and run Ollama]"
            return
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # Build optimized options for CPU inference
            options = {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            }
            
            # Add GPU/CPU settings
            if self.num_threads:
                options["num_thread"] = self.num_threads
            if self.num_ctx:
                options["num_ctx"] = self.num_ctx
            
            # Use explicit num_gpu. If -1, let Ollama handle it (often defaults to GPU if available)
            if self.num_gpu >= 0:
                options["num_gpu"] = self.num_gpu
            # else: do not set num_gpu, let Ollama auto-detect
            
            stream = self._client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                options=options,
            )
            
            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                    
        except Exception as e:
            logger.error(f"LLM streaming error: {e}")
            yield f"[Error: {e}]"
    
    def draft_resume(self, role: str, experience_years: int = 5, skills: Optional[list] = None) -> str:
        """Generate a professional resume."""
        skills_str = ", ".join(skills) if skills else "relevant skills"
        prompt = f"""Draft a professional resume for a {role} with {experience_years} years of experience.
Include sections for: Summary, Experience, Skills ({skills_str}), Education.
Make it concise but impactful. Use bullet points for achievements."""
        
        system = "You are a professional resume writer. Create ATS-friendly, achievement-focused resumes."
        return self.generate(prompt, system)
    
    def draft_sop(self, program: str, university: Optional[str] = None) -> str:
        """Generate a statement of purpose."""
        uni_str = f" at {university}" if university else ""
        prompt = f"""Write a compelling Statement of Purpose for applying to a {program} program{uni_str}.
Include: academic background, motivation, relevant experience, future goals.
Keep it personal and authentic. About 500-600 words."""
        
        system = "You are an expert in graduate school applications. Write compelling, genuine statements."
        return self.generate(prompt, system)
    
    def draft_email(self, purpose: str, recipient: Optional[str] = None) -> str:
        """Generate a professional email."""
        to_str = f" to {recipient}" if recipient else ""
        prompt = f"""Write a professional email{to_str} for the following purpose: {purpose}
Keep it concise, polite, and professional."""
        
        system = "You are a professional communication expert. Write clear, effective emails."
        return self.generate(prompt, system)
    
    def answer_question(self, question: str) -> str:
        """Answer a general question."""
        system = "You are Chintu, a helpful personal AI assistant. Be concise but thorough."
        return self.generate(question, system)
