"""AI-powered screening and multimodal PDF synthesis extraction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from synthesis_finder.chem_render import render_problem_structures
from synthesis_finder.llm_clients import (
    Attachment,
    MultiProviderLLM,
    extract_json_from_text,
)
from synthesis_finder.models import SynthesisProblem, SynthesisStep

SCREENING_SYSTEM_PROMPT = (
    "You are an organic chemistry expert. Decide whether a scientific article is a "
    "total synthesis, formal synthesis, or multi-step natural product / complex molecule "
    "synthesis suitable for an organic chemistry flashcard problem. "
    'Respond ONLY with JSON: {"is_candidate": true/false, "target_molecule": "...", "reason": "..."}.'
)

EXTRACTION_SYSTEM_PROMPT = (
    "You are an expert synthetic organic chemist. Extract the main total synthesis route "
    "from the provided paper into strict JSON. "
    "Provide valid canonical-style SMILES for the starting material and each step's product, "
    "along with concise reagents, reaction conditions, yield, named reaction (if applicable), "
    "and brief notes. Use 1-based step_index."
)

EXTRACTION_USER_TEMPLATE = """Extract the primary total synthesis route from this article.
Title: {title}

Return ONLY valid JSON with this exact schema:
{{
  "target_molecule": "Name of the target natural product or molecule",
  "start_smiles": "SMILES of the key starting material",
  "difficulty": "introductory | intermediate | advanced",
  "tags": ["total synthesis", "alkaloid", "..."],
  "steps": [
    {{
      "step_index": 1,
      "reagents": "e.g. Pd(PPh3)4, K2CO3",
      "conditions": "e.g. THF/H2O, 80 °C, 12 h",
      "yield": "e.g. 87%",
      "named_reaction": "e.g. Suzuki-Miyaura coupling",
      "product_smiles": "SMILES of the product after this step",
      "notes": "Brief key selectivity or mechanistic note"
    }}
  ]
}}"""


@dataclass
class ScreeningResult:
    """Result of LLM screening on article title + abstract."""

    is_candidate: bool
    target_molecule: str = ""
    reason: str = ""


@dataclass
class ExtractionResult:
    """Extracted synthesis problem plus catalog metadata."""

    problem: SynthesisProblem
    difficulty: str = "intermediate"
    tags: list[str] = field(default_factory=list)


def create_problem_id(doi: str = "", title: str = "") -> str:
    """Create a deterministic, filesystem-safe problem ID from DOI or title."""
    base = (doi or title or "problem").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    if len(slug) > 48:
        slug = slug[:48].rstrip("-")
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else f"prob-{digest}"


def screen_article(
    title: str,
    abstract: str = "",
    *,
    llm: MultiProviderLLM | None = None,
) -> ScreeningResult:
    """Screen title + abstract with a fast text LLM to check if it is a total synthesis paper."""
    client = llm or MultiProviderLLM()
    prompt = f"Title: {title}\n\nAbstract: {abstract or '(No abstract provided)'}"
    raw = client.generate_text(
        prompt,
        system_prompt=SCREENING_SYSTEM_PROMPT,
        json_mode=True,
        temperature=0.0,
    )
    data = extract_json_from_text(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object from screening LLM, got: {type(data).__name__}")
    return ScreeningResult(
        is_candidate=bool(data.get("is_candidate", False)),
        target_molecule=str(data.get("target_molecule") or ""),
        reason=str(data.get("reason") or ""),
    )


def is_total_synthesis_candidate(
    title: str,
    abstract: str = "",
    *,
    llm: MultiProviderLLM | None = None,
) -> bool:
    """Boolean convenience wrapper around screen_article for filter pipelines."""
    return screen_article(title, abstract, llm=llm).is_candidate


def _parse_extraction_payload(
    data: dict[str, Any],
    *,
    problem_id: str,
    title: str,
    authors: list[str] | None,
    journal: str,
    year: int | None,
    doi: str,
    pdf_url: str,
    source_url: str,
    render_svgs: bool = True,
) -> ExtractionResult:
    """Convert raw LLM JSON dict into a validated, rendered ExtractionResult."""
    raw_steps = data.get("steps") or []
    steps: list[SynthesisStep] = []
    for idx, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            continue
        step_data = dict(item)
        step_data.setdefault("step_index", idx)
        steps.append(SynthesisStep.from_dict(step_data))

    steps.sort(key=lambda s: s.step_index)

    problem = SynthesisProblem(
        id=problem_id,
        title=title,
        target_molecule=str(data.get("target_molecule") or ""),
        authors=list(authors or []),
        journal=journal,
        year=year,
        doi=doi,
        pdf_url=pdf_url,
        source_url=source_url,
        start_smiles=str(data.get("start_smiles") or ""),
        steps=steps,
    )
    if render_svgs:
        render_problem_structures(problem)

    difficulty = str(data.get("difficulty") or "intermediate").lower()
    if difficulty not in {"introductory", "intermediate", "advanced"}:
        difficulty = "intermediate"
    tags = [str(t) for t in (data.get("tags") or []) if str(t).strip()]

    return ExtractionResult(problem=problem, difficulty=difficulty, tags=tags)


def extract_synthesis_from_pdf(
    *,
    pdf_bytes: bytes | None = None,
    pdf_path: str | Path | None = None,
    title: str = "",
    authors: list[str] | None = None,
    journal: str = "",
    year: int | None = None,
    doi: str = "",
    pdf_url: str = "",
    source_url: str = "",
    problem_id: str | None = None,
    llm: MultiProviderLLM | None = None,
    render_svgs: bool = True,
) -> ExtractionResult:
    """Extract a structured SynthesisProblem from a PDF using Gemini multimodal."""
    if pdf_bytes is None:
        if pdf_path is None:
            raise ValueError("Either pdf_bytes or pdf_path must be provided.")
        pdf_bytes = Path(pdf_path).read_bytes()

    client = llm or MultiProviderLLM()
    prompt = EXTRACTION_USER_TEMPLATE.format(title=title or "Unknown Title")
    raw = client.generate_multimodal(
        prompt,
        attachments=[Attachment(data=pdf_bytes, mime_type="application/pdf")],
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        json_mode=True,
        temperature=0.1,
    )
    data = extract_json_from_text(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object from extraction LLM, got: {type(data).__name__}")

    pid = problem_id or create_problem_id(doi=doi, title=title)
    return _parse_extraction_payload(
        data,
        problem_id=pid,
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        doi=doi,
        pdf_url=pdf_url,
        source_url=source_url,
        render_svgs=render_svgs,
    )
