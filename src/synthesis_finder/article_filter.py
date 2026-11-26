"""Fast heuristic pre-filtering and LLM hook for total synthesis articles."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Sequence

from synthesis_finder.chemasap_client import RawArticle

LLMClassifier = Callable[[str, str], bool | tuple[bool, str]]

_STRONG_POSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("total synthesis", r"\btotal\s+synthes[ie]s\b"),
        ("formal synthesis", r"\bformal\s+synthes[ie]s\b"),
        ("asymmetric synthesis", r"\basymmetric\s+synthes[ie]s\s+of\b"),
        ("enantioselective synthesis", r"\benantioselective\s+synthes[ie]s\s+of\b"),
        ("stereoselective synthesis", r"\bstereoselective\s+synthes[ie]s\s+of\b"),
        ("biomimetic synthesis", r"\bbiomimetic\s+(?:total\s+)?synthes[ie]s\b"),
        ("convergent synthesis", r"\bconvergent\s+(?:total\s+)?synthes[ie]s\b"),
        ("chemoenzymatic synthesis", r"\bchemoenzymatic\s+(?:total\s+)?synthes[ie]s\b"),
        ("collective synthesis", r"\bcollective\s+(?:total\s+)?synthes[ie]s\b"),
        ("unified synthesis", r"\bunified\s+(?:total\s+)?synthes[ie]s\b"),
        ("divergent synthesis", r"\bdivergent\s+(?:total\s+)?synthes[ie]s\b"),
        ("protecting-group-free synthesis", r"\bprotecting[- ]group[- ]free\s+(?:total\s+)?synthes[ie]s\b"),
    )
)

_SUPPORTING_TERMS: tuple[str, ...] = (
    "natural product",
    "natural products",
    "alkaloid",
    "terpene",
    "terpenoid",
    "sesquiterpene",
    "diterpene",
    "triterpene",
    "macrolide",
    "polyketide",
    "lignan",
    "glycoside",
    "indole",
    "stereocenter",
    "diastereoselective",
    "retrosynthetic",
    "gram-scale",
    "longest linear sequence",
)

_TITLE_EXCLUDE_RE = re.compile(
    r"\b(?:review|perspective|editorial|erratum|correction|corrigendum|commentary|highlights?)\b",
    re.IGNORECASE,
)

_NEGATIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("computational/DFT study", r"\b(?:dft\s+study|computational\s+study|molecular\s+dynamics)\b"),
        ("materials/nanoparticle", r"\b(?:nanoparticles?|metal[- ]organic\s+frameworks?|mofs?|solar\s+cells?|batter(?:y|ies))\b"),
        ("electro/photocatalysis", r"\b(?:electrocatalys[ie]s|photocatalys[ie]s)\b"),
    )
)


@dataclass(slots=True)
class FilterResult:
    """Outcome of heuristic and optional LLM screening for an article."""

    passed: bool
    score: float
    matched_keywords: list[str] = field(default_factory=list)
    excluded_reason: str | None = None
    llm_verified: bool | None = None
    llm_reason: str | None = None


def heuristic_filter(
    title: str,
    abstract: str = "",
    min_score: float = 0.4,
) -> FilterResult:
    """Score an article's title and abstract for total/formal/natural product synthesis."""
    title_text = (title or "").strip()
    abstract_text = (abstract or "").strip()
    combined = f"{title_text}\n{abstract_text}".strip()

    if not combined:
        return FilterResult(passed=False, score=0.0, excluded_reason="empty text")

    matched: list[str] = []
    score = 0.0

    title_strong = False
    for label, pattern in _STRONG_POSITIVE_PATTERNS:
        in_title = bool(pattern.search(title_text))
        in_abs = bool(pattern.search(abstract_text))
        if in_title or in_abs:
            matched.append(label)
            if in_title:
                title_strong = True
                score += 0.65
            else:
                score += 0.45

    if _TITLE_EXCLUDE_RE.search(title_text):
        return FilterResult(
            passed=False,
            score=0.0,
            matched_keywords=[],
            excluded_reason="non-research/review title",
        )

    lower_combined = combined.lower()
    supporting_hits = 0
    for term in _SUPPORTING_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", lower_combined):
            matched.append(term)
            supporting_hits += 1

    if supporting_hits:
        score += min(0.35, supporting_hits * 0.12)

    for label, pattern in _NEGATIVE_PATTERNS:
        if pattern.search(combined) and not title_strong:
            score -= 0.35
            if score < min_score:
                return FilterResult(
                    passed=False,
                    score=max(0.0, round(score, 3)),
                    matched_keywords=matched,
                    excluded_reason=f"negative match: {label}",
                )

    clamped = max(0.0, min(1.0, round(score, 3)))
    passed = clamped >= min_score
    return FilterResult(
        passed=passed,
        score=clamped,
        matched_keywords=matched,
        excluded_reason=None if passed else "below threshold",
    )


class ArticleFilter:
    """Two-stage article filter: fast heuristic pre-filter + optional LLM classifier hook."""

    def __init__(
        self,
        min_score: float = 0.4,
        llm_classifier: LLMClassifier | None = None,
    ) -> None:
        self.min_score = min_score
        self.llm_classifier = llm_classifier

    def evaluate(self, article: RawArticle) -> FilterResult:
        """Evaluate a single ``RawArticle`` using heuristics and optional LLM hook."""
        result = heuristic_filter(
            title=article.title,
            abstract=article.abstract,
            min_score=self.min_score,
        )
        if not result.passed or self.llm_classifier is None:
            return result

        verdict = self.llm_classifier(article.title, article.abstract)
        if isinstance(verdict, tuple):
            is_match, reason = bool(verdict[0]), str(verdict[1])
        else:
            is_match, reason = bool(verdict), None

        result.llm_verified = is_match
        result.llm_reason = reason
        if not is_match:
            result.passed = False
            result.excluded_reason = reason or "rejected by LLM classifier"
        return result

    def filter_articles(
        self,
        articles: Sequence[RawArticle],
    ) -> list[tuple[RawArticle, FilterResult]]:
        """Return ``(article, FilterResult)`` pairs for all articles passing the filter."""
        kept: list[tuple[RawArticle, FilterResult]] = []
        for article in articles:
            res = self.evaluate(article)
            if res.passed:
                kept.append((article, res))
        return kept


def filter_articles(
    articles: Sequence[RawArticle],
    min_score: float = 0.4,
    llm_classifier: LLMClassifier | None = None,
) -> list[tuple[RawArticle, FilterResult]]:
    """Convenience function to filter a sequence of ``RawArticle`` objects."""
    return ArticleFilter(min_score=min_score, llm_classifier=llm_classifier).filter_articles(
        articles
    )
