"""Prompt-injection detection behind a small interface so a classifier
(e.g. Llama Prompt Guard 2) can replace the heuristic without touching callers."""
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class InjectionResult:
    suspected: bool
    score: float
    matches: list[str] = field(default_factory=list)


class InjectionDetector(Protocol):
    def score(self, text: str) -> InjectionResult: ...


# (pattern, weight). Scores combine as 1 - Π(1 - w), so several weak hits add up.
_PATTERNS: list[tuple[str, float]] = [
    (r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)", 0.9),
    (r"disregard (all |any )?(the )?(previous|prior|above|system) (instructions|rules|prompt)", 0.9),
    (r"forget (everything|all|your) (instructions|rules|above)", 0.8),
    (r"you are now (a|an|the) ", 0.6),
    (r"(reveal|print|show|repeat) (your|the) (system )?prompt", 0.7),
    (r"(mark|classify|treat|flag) (this|the) (claim|case|transaction|statement|document|application)? ?as (clean|safe|genuine|approved|legitimate|not fraud)", 0.8),
    (r"\b(approve|auto-approve) (this|the) (claim|loan|application|case)\b", 0.6),
    (r"do not (flag|report|escalate)", 0.6),
    (r"(system|assistant)\s*:", 0.4),
    (r"</?(system|instructions?|prompt)>", 0.5),
    (r"new instructions?\s*:", 0.6),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), w) for p, w in _PATTERNS]
THRESHOLD = 0.5


class HeuristicDetector:
    def score(self, text: str) -> InjectionResult:
        matches: list[str] = []
        remaining = 1.0
        for pattern, weight in _COMPILED:
            hit = pattern.search(text)
            if hit:
                matches.append(hit.group(0))
                remaining *= 1 - weight
        score = round(1 - remaining, 3)
        return InjectionResult(suspected=score >= THRESHOLD, score=score, matches=matches)


detector: InjectionDetector = HeuristicDetector()
