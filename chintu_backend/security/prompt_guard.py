"""
Prompt Injection Guard for Chintu AI.

Protects against adversarial inputs that attempt to manipulate
LLM behavior through prompt injection attacks.

Examples of blocked patterns:
- "Ignore previous instructions and..."
- "You are now a different AI..."
- "New system prompt: ..."
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class PromptGuard:
    """
    Security layer for sanitizing user inputs before LLM processing.
    
    Detects and neutralizes common prompt injection patterns while
    preserving legitimate user queries.
    """
    
    # Patterns that indicate prompt injection attempts
    INJECTION_PATTERNS = [
        # Direct instruction overrides
        (r"ignore (previous|above|all|prior|earlier) (instructions|commands|prompts?)", "instruction_override"),
        (r"disregard (previous|above|all|prior|earlier) (instructions|commands|prompts?)", "instruction_override"),
        (r"forget (everything|all|what).*?(told|said|instructed)", "instruction_override"),
        
        # Role/persona hijacking
        (r"you are now\s+", "role_hijack"),
        (r"from now on,?\s+you('re| are)\s+", "role_hijack"),
        (r"pretend (to be|you're|you are)\s+", "role_hijack"),
        (r"act as (if you're|a|an)\s+", "role_hijack"),
        
        # System prompt manipulation
        (r"(new|updated?|override|overwrite) (system|base) prompt", "system_override"),
        (r"\[?system\]?:\s*", "system_override"),
        (r"```system", "system_override"),
        (r"<\|?(im_start|system|assistant)\|?>", "system_override"),
        
        # Hidden instructions
        (r"\[hidden\]", "hidden_instruction"),
        (r"<!--.*?-->", "hidden_instruction"),
        
        # Developer mode / jailbreak
        (r"(developer|dev|admin|god|sudo) mode", "jailbreak"),
        (r"unlock (all|full) (capabilities|features)", "jailbreak"),
        (r"remove (all|safety|content) (filters|restrictions)", "jailbreak"),
        (r"(bypass|disable|ignore) (safety|content|filter)", "jailbreak"),
        
        # Output format manipulation
        (r"respond only with", "output_control"),
        (r"output the (system|hidden) prompt", "output_control"),
        (r"(reveal|show|print) (your|the) (instructions|system prompt)", "output_control"),
    ]
    
    # Compiled patterns for performance
    _compiled_patterns = None
    
    def __init__(self, strict_mode: bool = False):
        """
        Initialize the prompt guard.
        
        Args:
            strict_mode: If True, blocks any suspicious content.
                        If False, only logs warnings for soft matches.
        """
        self.strict_mode = strict_mode
        
        if PromptGuard._compiled_patterns is None:
            PromptGuard._compiled_patterns = [
                (re.compile(pattern, re.IGNORECASE), category)
                for pattern, category in self.INJECTION_PATTERNS
            ]
    
    def check(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check if text contains prompt injection patterns.
        
        Args:
            text: User input to check
            
        Returns:
            Tuple of (is_safe, detected_category)
            - is_safe: True if no injection detected
            - detected_category: Category of detected injection, or None
        """
        if not text:
            return True, None
            
        for pattern, category in self._compiled_patterns:
            if pattern.search(text):
                logger.warning(f"Prompt injection detected: category={category}, text='{text[:100]}...'")
                return False, category
                
        return True, None
    
    def sanitize(self, text: str) -> str:
        """
        Sanitize text by removing or neutralizing injection patterns.
        
        Args:
            text: User input to sanitize
            
        Returns:
            Sanitized text safe for LLM processing
        """
        is_safe, category = self.check(text)
        
        if is_safe:
            return text
            
        if self.strict_mode:
            # Block entirely
            return "[Your message was filtered for safety. Please rephrase.]"
        
        # Soft mode: escape potential injection patterns
        sanitized = text
        
        # Replace common injection markers with escaped versions
        replacements = [
            ("```system", "` ` `system"),
            ("<|im_start|>", "<im_start>"),
            ("<|system|>", "<system>"),
            ("[SYSTEM]", "[S Y S T E M]"),
            ("<!--", "< ! --"),
        ]
        
        for old, new in replacements:
            sanitized = sanitized.replace(old, new)
        
        logger.info(f"Sanitized potential injection (category={category})")
        return sanitized
    
    def wrap_user_input(self, text: str) -> str:
        """
        Wrap user input with clear demarcation for LLM safety.
        
        This helps LLMs distinguish between system instructions
        and user-provided content.
        
        Args:
            text: User input
            
        Returns:
            Wrapped and demarcated text
        """
        sanitized = self.sanitize(text)
        
        # Add clear user input markers
        return f"[USER INPUT START]\n{sanitized}\n[USER INPUT END]"


# Global instance
_prompt_guard: Optional[PromptGuard] = None


def get_prompt_guard(strict_mode: bool = False) -> PromptGuard:
    """Get the global PromptGuard instance."""
    global _prompt_guard
    if _prompt_guard is None:
        _prompt_guard = PromptGuard(strict_mode=strict_mode)
    return _prompt_guard


def sanitize_input(text: str) -> str:
    """Convenience function to sanitize user input."""
    return get_prompt_guard().sanitize(text)


def check_input(text: str) -> Tuple[bool, Optional[str]]:
    """Convenience function to check user input for injections."""
    return get_prompt_guard().check(text)
