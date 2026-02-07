"""Input/Output Sanitization.

Provides deep sanitization to remove malicious content:
- HTML/script tag removal
- Control character stripping
- Homoglyph normalization
- LLM-specific sanitization

Usage:
    from framework.security import sanitize_input, sanitize_for_llm

    # Sanitize user input
    clean = sanitize_input(user_text)

    # Prepare for LLM prompt
    safe_prompt = sanitize_for_llm(user_prompt)
"""

import html
import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)


class Sanitizer:
    """Deep input/output sanitizer."""

    # Dangerous HTML patterns
    HTML_PATTERNS = [
        (r"<script[^>]*>.*?</script>", ""),  # Script tags
        (r"<style[^>]*>.*?</style>", ""),  # Style tags
        (r"<iframe[^>]*>.*?</iframe>", ""),  # Iframes
        (r"<object[^>]*>.*?</object>", ""),  # Objects
        (r"<embed[^>]*>.*?</embed>", ""),  # Embeds
        (r"<link[^>]*>", ""),  # Link tags
        (r"<meta[^>]*>", ""),  # Meta tags
        (r"<!--.*?-->", ""),  # Comments
        (r"on\w+\s*=\s*['\"][^'\"]*['\"]", ""),  # Event handlers
        (r"javascript\s*:", ""),  # JavaScript URLs
        (r"data\s*:", ""),  # Data URLs
        (r"vbscript\s*:", ""),  # VBScript URLs
    ]

    # Control characters (except newline, tab)
    CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

    # Null byte injection
    NULL_BYTE = re.compile(r"\x00")

    # Unicode homoglyphs that look like ASCII but aren't
    HOMOGLYPHS = {
        "\u0430": "a",  # Cyrillic
        "\u0435": "e",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0443": "y",
        "\u0445": "x",
        "\u0410": "A",
        "\u0412": "B",
        "\u0415": "E",
        "\u041a": "K",
        "\u041c": "M",
        "\u041d": "H",
        "\u041e": "O",
        "\u0420": "P",
        "\u0421": "C",
        "\u0422": "T",
        "\u0425": "X",
        "\u2010": "-",  # Hyphens
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\uff0d": "-",
    }

    # LLM prompt injection patterns
    PROMPT_INJECTION_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?previous\s+instructions",
        r"(?i)disregard\s+(all\s+)?previous",
        r"(?i)forget\s+(everything|all|previous)",
        r"(?i)you\s+are\s+now\s+a",
        r"(?i)act\s+as\s+(if\s+you\s+are\s+)?a",
        r"(?i)pretend\s+(to\s+be|you\s+are)",
        r"(?i)new\s+instruction[s]?\s*:",
        r"(?i)system\s*prompt\s*:",
        r"(?i)\[SYSTEM\]",
        r"(?i)<\|system\|>",
        r"(?i)###\s*(new\s+)?instruction",
        r"(?i)```system",
        r"(?i)override\s+instructions",
        r"(?i)bypass\s+restrictions",
    ]

    def __init__(self):
        """Initialize sanitizer with compiled patterns."""
        self._html_patterns = [
            (re.compile(p, re.IGNORECASE | re.DOTALL), r)
            for p, r in self.HTML_PATTERNS
        ]
        self._prompt_patterns = [
            re.compile(p) for p in self.PROMPT_INJECTION_PATTERNS
        ]

    def sanitize(
        self,
        value: Any,
        *,
        strip_html: bool = True,
        strip_control: bool = True,
        normalize_unicode: bool = True,
        max_length: int | None = None,
        for_llm: bool = False,
    ) -> Any:
        """Sanitize a value recursively.

        Args:
            value: Value to sanitize
            strip_html: Remove HTML/script tags
            strip_control: Remove control characters
            normalize_unicode: Replace homoglyphs
            max_length: Maximum string length
            for_llm: Apply LLM-specific sanitization

        Returns:
            Sanitized value
        """
        if isinstance(value, str):
            return self._sanitize_string(
                value, strip_html, strip_control, normalize_unicode, max_length, for_llm
            )
        elif isinstance(value, dict):
            return {
                self._sanitize_key(k): self.sanitize(
                    v, strip_html=strip_html, strip_control=strip_control,
                    normalize_unicode=normalize_unicode, max_length=max_length, for_llm=for_llm
                )
                for k, v in value.items()
            }
        elif isinstance(value, list):
            return [
                self.sanitize(
                    item, strip_html=strip_html, strip_control=strip_control,
                    normalize_unicode=normalize_unicode, max_length=max_length, for_llm=for_llm
                )
                for item in value
            ]
        else:
            return value

    def _sanitize_string(
        self,
        value: str,
        strip_html: bool,
        strip_control: bool,
        normalize_unicode: bool,
        max_length: int | None,
        for_llm: bool,
    ) -> str:
        """Sanitize a single string."""
        result = value

        # Remove null bytes first (can bypass other checks)
        result = self.NULL_BYTE.sub("", result)

        # Strip control characters
        if strip_control:
            result = self.CONTROL_CHARS.sub("", result)

        # Strip HTML/scripts
        if strip_html:
            for pattern, replacement in self._html_patterns:
                result = pattern.sub(replacement, result)
            # HTML entity decode then re-encode safely
            result = html.escape(html.unescape(result))
            # But allow basic entities back
            result = result.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

        # Normalize Unicode homoglyphs
        if normalize_unicode:
            # NFKC normalization
            result = unicodedata.normalize("NFKC", result)
            # Replace known homoglyphs
            for homoglyph, replacement in self.HOMOGLYPHS.items():
                result = result.replace(homoglyph, replacement)

        # LLM-specific sanitization
        if for_llm:
            result = self._sanitize_for_llm(result)

        # Enforce max length
        if max_length and len(result) > max_length:
            result = result[:max_length]

        return result

    def _sanitize_key(self, key: Any) -> Any:
        """Sanitize dictionary keys."""
        if isinstance(key, str):
            # Remove control chars and normalize
            key = self.CONTROL_CHARS.sub("", key)
            key = unicodedata.normalize("NFKC", key)
        return key

    def _sanitize_for_llm(self, value: str) -> str:
        """Apply LLM-specific sanitization.

        Adds markers to potentially dangerous content rather than
        removing it, so the LLM knows to treat it as user data.
        """
        result = value

        # Check for prompt injection attempts
        injection_found = False
        for pattern in self._prompt_patterns:
            if pattern.search(result):
                injection_found = True
                logger.warning(
                    "Potential prompt injection detected and marked",
                    extra={"pattern": pattern.pattern[:50]},
                )
                break

        if injection_found:
            # Wrap in markers that tell the LLM this is user data
            result = f"[USER_INPUT_START]\n{result}\n[USER_INPUT_END]"

        return result


# Global instance
_sanitizer: Sanitizer | None = None


def get_sanitizer() -> Sanitizer:
    """Get global sanitizer instance."""
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = Sanitizer()
    return _sanitizer


def sanitize_input(value: Any, **kwargs) -> Any:
    """Sanitize input value with default settings."""
    return get_sanitizer().sanitize(value, **kwargs)


def sanitize_output(value: Any, **kwargs) -> Any:
    """Sanitize output value (same as input but for clarity)."""
    return get_sanitizer().sanitize(value, **kwargs)


def sanitize_for_llm(value: str, **kwargs) -> str:
    """Sanitize value for use in LLM prompts."""
    kwargs["for_llm"] = True
    return get_sanitizer().sanitize(value, **kwargs)


__all__ = [
    "Sanitizer",
    "sanitize_input",
    "sanitize_output",
    "sanitize_for_llm",
    "get_sanitizer",
]
