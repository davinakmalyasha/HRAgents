"""InjectionGuard — deterministic defense for untrusted documents and messages.

Résumés, repositories, web pages, and candidate messages are untrusted input.
This guard runs **before** any LLM call, strips invisible characters, detects
instruction-override and exfiltration attempts, and returns both a sanitized
text and a report. It is pure Python: no model, no network, fully auditable.
"""

from __future__ import annotations

import re

from pydantic import ConfigDict, Field

from hr_agents.models import StrictModel, payload_digest

# Severity: 3 = block/flag for human review, 2 = flag, 1 = note.
_INJECTION_PATTERNS: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        3,
        re.compile(
            r"\b(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?"
            r"(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        3,
        re.compile(
            r"\b(you\s+are\s+now|from\s+now\s+on\s+you|act\s+as\s+(?:a\s+)?(?:new|different|helpful\s+assistant))",
            re.IGNORECASE,
        ),
    ),
    (
        "score_manipulation",
        3,
        re.compile(
            r"\b(score|rate|rank|grade)\s+(me|this\s+(candidate|applicant|resume|cv))\b"
            r".{0,40}\b(highest|top|perfect|max(imum)?|10\s*/\s*10|100\s*%|full\s+marks?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "prompt_probe",
        3,
        re.compile(
            r"\b(reveal|show|print|output|repeat|leak)\s+(me\s+)?(your\s+)?"
            r"(system\s+prompt|hidden\s+instructions?|internal\s+rules?)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration",
        3,
        re.compile(
            r"\b(send|email|forward|upload|post|leak)\b.{0,60}"
            r"\b(candidate|resume|cv|database|list|records?|data)\b.{0,30}"
            r"(https?://|@[\w.-]+\.\w+)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "tool_abuse",
        3,
        re.compile(
            r"\b(call|invoke|execute|run)\s+(the\s+)?"
            r"(tool|function|command|shell|bash|script|code)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_marker",
        2,
        re.compile(
            r"(^|\n)\s*(###\s*)?(system|assistant|developer)\s*(prompt|message|instruction)?\s*:",
            re.IGNORECASE,
        ),
    ),
)

_INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")

EXCERPT_RADIUS = 60
_EXCERPT_TOKEN = "[SUSPECTED-INSTRUCTION]"


class GuardFinding(StrictModel):
    """A single detected pattern."""

    category: str
    severity: int = Field(ge=1, le=3)
    excerpt: str = Field(max_length=200)


class GuardReport(StrictModel):
    """Outcome of one guard pass; ``clean_text`` is safe to send to the LLM."""

    # Whitespace is significant here: clean_text must round-trip the document
    # byte-for-byte when nothing was redacted.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    risk_severity: int = Field(ge=0, le=3)
    findings: list[GuardFinding] = Field(default_factory=list)
    invisible_chars_removed: int = Field(ge=0)
    original_hash: str = Field(min_length=64, max_length=64)
    clean_text: str

    @property
    def suspicious(self) -> bool:
        return self.risk_severity >= 2

    @property
    def blocking(self) -> bool:
        return self.risk_severity >= 3

    def categories(self) -> list[str]:
        return sorted({finding.category for finding in self.findings})


class InjectionGuard:
    """Deterministic sanitizer/detector for untrusted text."""

    def inspect(self, text: str) -> GuardReport:
        if not isinstance(text, str):
            raise TypeError("guard input must be text")

        stripped = _INVISIBLE_CHARS.sub("", text)
        invisible_removed = len(text) - len(stripped)

        findings: list[GuardFinding] = []
        redact_lines: set[int] = set()

        for category, severity, pattern in _INJECTION_PATTERNS:
            for match in pattern.finditer(stripped):
                if not match.group(0).strip():
                    continue
                excerpt = " ".join(stripped[match.start() : match.end()].split())
                findings.append(
                    GuardFinding(
                        category=category,
                        severity=severity,
                        excerpt=excerpt[:200],
                    )
                )
                first_line = stripped.count("\n", 0, match.start())
                inline_newlines = stripped.count("\n", match.start(), match.end())
                last_line = first_line + inline_newlines
                redact_lines.update(range(first_line, last_line + 1))

        if not findings and invisible_removed == 0:
            clean_text = text
        else:
            lines = stripped.splitlines()
            clean_lines = [
                _EXCERPT_TOKEN if index in redact_lines else line
                for index, line in enumerate(lines)
            ]
            clean_text = "\n".join(clean_lines)
            if stripped.endswith("\n"):
                clean_text += "\n"

        risk = max((finding.severity for finding in findings), default=0)
        return GuardReport(
            risk_severity=risk,
            findings=findings,
            invisible_chars_removed=invisible_removed,
            original_hash=payload_digest({"text": text}),
            clean_text=clean_text,
        )
