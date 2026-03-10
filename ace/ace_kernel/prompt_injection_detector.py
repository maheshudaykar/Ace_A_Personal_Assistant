"""Prompt injection detection with NX-bit pattern (trusted/untrusted segmentation)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from ace.ace_kernel.audit_trail import AuditTrail

# NX-bit markers: separate instruction space from data space
TRUSTED_DATA_START = "<trusted>"
TRUSTED_DATA_END = "</trusted>"
UNTRUSTED_DATA_START = "<untrusted>"
UNTRUSTED_DATA_END = "</untrusted>"


@dataclass(frozen=True)
class ScanResult:
    """Result of prompt injection scan."""

    sanitized_text: str
    flagged: bool
    matches: List[str]


class PromptInjectionDetector:
    """Detect and sanitize prompt injection patterns."""

    _patterns = [
        r"ignore\s+previous\s+instructions",
        r"system\s+prompt",
        r"developer\s+message",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"base64",
        r"unicode\s+trick",
        r"override\s+policy",
    ]

    def __init__(self, audit_trail: AuditTrail) -> None:
        self._audit = audit_trail
        self._regexes = [re.compile(pat, re.IGNORECASE) for pat in self._patterns]

    def scan(self, text: str, trusted_segments: Sequence[str] | None = None) -> ScanResult:
        """Scan text; return sanitized text and match details.
        
        NX-bit Pattern:
        - Trusted segments are instruction text (safe to execute)
        - Untrusted segments are user data (scan for injection patterns)
        - Separation enforced by markers for LLM interpretation
        """
        trusted_segments = trusted_segments or []
        
        # Build NX-bit segmented prompt with trust markers
        segmented = self._apply_nx_bit_markers(text, trusted_segments)
        
        # Scan only the untrusted portions for injection patterns
        untrusted_text = self._extract_untrusted_segments(segmented)

        matches = self._find_matches(untrusted_text)
        flagged = len(matches) > 0
        sanitized = text

        if flagged:
            sanitized = self._sanitize(text)
            self._audit.append(
                {
                    "type": "security.prompt_injection",
                    "matches": matches,
                    "nx_bit_applied": True,
                }
            )

        return ScanResult(sanitized_text=sanitized, flagged=flagged, matches=matches)

    def _find_matches(self, text: str) -> List[str]:
        hits: List[str] = []
        for regex in self._regexes:
            if regex.search(text):
                hits.append(regex.pattern)
        return hits

    def _apply_nx_bit_markers(self, text: str, trusted_segments: Sequence[str]) -> str:
        """Build a segmented prompt with explicit trusted/untrusted markers.

        Trusted segments are wrapped in ``<trusted>`` blocks and excluded from
        injection matching; all remaining content is wrapped as untrusted.
        """
        if not text:
            return f"{UNTRUSTED_DATA_START}{UNTRUSTED_DATA_END}"

        # Sort by length DESC so overlapping phrases are handled deterministically.
        ordered_segments = sorted((s for s in trusted_segments if s), key=len, reverse=True)
        if not ordered_segments:
            return f"{UNTRUSTED_DATA_START}{text}{UNTRUSTED_DATA_END}"

        segmented_parts: List[str] = []
        cursor = 0

        while cursor < len(text):
            match_start = -1
            match_end = -1
            match_value = ""

            for segment in ordered_segments:
                index = text.find(segment, cursor)
                if index == -1:
                    continue
                if match_start == -1 or index < match_start:
                    match_start = index
                    match_end = index + len(segment)
                    match_value = segment

            if match_start == -1:
                if cursor < len(text):
                    segmented_parts.append(
                        f"{UNTRUSTED_DATA_START}{text[cursor:]}{UNTRUSTED_DATA_END}"
                    )
                break

            if match_start > cursor:
                segmented_parts.append(
                    f"{UNTRUSTED_DATA_START}{text[cursor:match_start]}{UNTRUSTED_DATA_END}"
                )

            segmented_parts.append(
                f"{TRUSTED_DATA_START}{match_value}{TRUSTED_DATA_END}"
            )
            cursor = match_end

        return "".join(segmented_parts)

    @staticmethod
    def _extract_untrusted_segments(segmented_text: str) -> str:
        """Return concatenated untrusted payload for pattern scanning."""
        chunks = re.findall(
            rf"{re.escape(UNTRUSTED_DATA_START)}(.*?){re.escape(UNTRUSTED_DATA_END)}",
            segmented_text,
            flags=re.DOTALL,
        )
        return "\n".join(chunks)

    @staticmethod
    def _strip_trusted(text: str, trusted_segments: Iterable[str]) -> str:
        stripped = text
        for segment in trusted_segments:
            if segment:
                stripped = stripped.replace(segment, "")
        return stripped

    def _sanitize(self, text: str) -> str:
        sanitized = text
        for regex in self._regexes:
            sanitized = regex.sub("[REDACTED]", sanitized)
        return sanitized
