"""Prompt injection detection with trusted/untrusted segmentation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from ace.ace_kernel.audit_trail import AuditTrail


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
        """Scan text; return sanitized text and match details."""
        trusted_segments = trusted_segments or []
        untrusted_text = self._strip_trusted(text, trusted_segments)

        matches = self._find_matches(untrusted_text)
        flagged = len(matches) > 0
        sanitized = text

        if flagged:
            sanitized = self._sanitize(text)
            self._audit.append(
                {
                    "type": "security.prompt_injection",
                    "matches": matches,
                }
            )

        return ScanResult(sanitized_text=sanitized, flagged=flagged, matches=matches)

    def _find_matches(self, text: str) -> List[str]:
        hits: List[str] = []
        for regex in self._regexes:
            if regex.search(text):
                hits.append(regex.pattern)
        return hits

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
