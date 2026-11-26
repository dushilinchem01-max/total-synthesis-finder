"""AI-powered screening and PDF scheme-cropping synthesis extraction."""

from __future__ import annotations

import hashlib
import logging
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
from synthesis_finder.pdf_cropper import (
    crop_box_2d,
    image_to_data_uri,
    image_to_png_bytes,
    render_pdf_pages,
)

logger = logging.getLogger(__name__)

SCREENING_SYSTEM_PROMPT = (
    "You are an organic chemistry expert. Decide whether a scientific article is a "
    "total synthesis, formal synthesis, or multi-step natural product / complex molecule "
    "synthesis suitable for an organic chemistry flashcard problem. "
    'Respond ONLY with JSON: {"is_candidate": true/false, "target_molecule": "...", "reason": "..."}.'
)

LOCATE_SCHEME_PROMPT = """Inspect this chemistry paper PDF and identify which page(s) contain the MAIN total synthesis scheme (showing the multi-step route with arrows, reagents, and intermediate structures toward the target molecule).

Title: {title}

Return ONLY valid JSON:
{{
  "target_molecule": "Name of the target molecule",
  "difficulty": "introductory | intermediate | advanced",
  "tags": ["total synthesis", "..."],
  "scheme_pages": [0]
}}
Note: scheme_pages must be 0-based page indices (e.g., page 1 is 0, page 2 is 1). Pick at most 2 main scheme pages."""

CROP_SCHEME_SYSTEM_PROMPT = (
    "You are an expert organic chemist and vision annotator. "
    "Given a high-resolution image of a chemistry paper page containing a total synthesis scheme, "
    "locate each chemical structure in the main synthesis sequence using normalized bounding boxes "
    "[ymin, xmin, ymax, xmax] on a 0-1000 scale, and transcribe the reagents, conditions, yield, "
    "and named reaction for each step arrow."
)

CROP_SCHEME_USER_TEMPLATE = """Extract the total synthesis sequence shown on this page for "{target_molecule}".

For every molecule in the main linear/convergent sequence, provide a tight bounding box [ymin, xmin, ymax, xmax] (0 to 1000) around the chemical structure ONLY (do not include adjacent reaction arrows or unrelated text).

Return ONLY valid JSON with this exact schema:
{{
  "start_box_2d": [ymin, xmin, ymax, xmax],
  "steps": [
    {{
      "step_index": 1,
      "reagents": "e.g. Pd(PPh3)4, K2CO3",
      "conditions": "e.g. THF/H2O, 80 °C, 12 h",
      "yield": "e.g. 87%",
      "named_reaction": "e.g. Suzuki-Miyaura coupling",
      "product_box_2d": [ymin, xmin, ymax, xmax],
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
    """Convert raw LLM JSON dict (SMILES-based fallback) into a validated ExtractionResult."""
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
    dpi: int = 220,
) -> ExtractionResult:
    """Extract a structured SynthesisProblem by locating scheme pages and cropping structures from PDF."""
    if pdf_bytes is None:
        if pdf_path is None:
            raise ValueError("Either pdf_bytes or pdf_path must be provided.")
        pdf_bytes = Path(pdf_path).read_bytes()

    client = llm or MultiProviderLLM()
    pid = problem_id or create_problem_id(doi=doi, title=title)

    # Pass 1: Locate scheme page(s) and metadata from the PDF
    locate_raw = client.generate_multimodal(
        LOCATE_SCHEME_PROMPT.format(title=title or "Unknown Title"),
        attachments=[Attachment(data=pdf_bytes, mime_type="application/pdf")],
        json_mode=True,
        temperature=0.1,
    )
    locate_data = extract_json_from_text(locate_raw)
    if not isinstance(locate_data, dict):
        raise ValueError(f"Expected JSON object from locate step, got: {type(locate_data).__name__}")

    # Backwards-compatible path if caller/mock returned full steps directly in Pass 1
    if "steps" in locate_data and "scheme_pages" not in locate_data:
        return _parse_extraction_payload(
            locate_data,
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

    target_molecule = str(locate_data.get("target_molecule") or title or "Target Molecule")
    difficulty = str(locate_data.get("difficulty") or "intermediate").lower()
    if difficulty not in {"introductory", "intermediate", "advanced"}:
        difficulty = "intermediate"
    tags = [str(t) for t in (locate_data.get("tags") or []) if str(t).strip()]

    scheme_pages = [int(p) for p in (locate_data.get("scheme_pages") or [0]) if str(p).isdigit()]
    if not scheme_pages:
        scheme_pages = [0]

    # Render PDF pages at high DPI
    page_images = render_pdf_pages(pdf_bytes=pdf_bytes, dpi=dpi, max_pages=max(scheme_pages) + 1)
    if not page_images:
        raise ValueError("PDF rendered 0 pages.")

    start_image_uri = ""
    all_steps: list[SynthesisStep] = []
    step_counter = 1

    for page_idx in scheme_pages[:2]:
        if page_idx < 0 or page_idx >= len(page_images):
            continue
        page_img = page_images[page_idx]
        page_png = image_to_png_bytes(page_img)

        crop_raw = client.generate_multimodal(
            CROP_SCHEME_USER_TEMPLATE.format(target_molecule=target_molecule),
            attachments=[Attachment(data=page_png, mime_type="image/png")],
            system_prompt=CROP_SCHEME_SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.1,
        )
        crop_data = extract_json_from_text(crop_raw)
        if not isinstance(crop_data, dict):
            continue

        if not start_image_uri and isinstance(crop_data.get("start_box_2d"), list):
            try:
                start_crop = crop_box_2d(page_img, crop_data["start_box_2d"])
                start_image_uri = image_to_data_uri(start_crop)
            except Exception as exc:
                logger.warning("Failed to crop start_box_2d on page %d: %s", page_idx, exc)

        for raw_step in crop_data.get("steps") or []:
            if not isinstance(raw_step, dict):
                continue
            prod_uri = ""
            box = raw_step.get("product_box_2d")
            if isinstance(box, list):
                try:
                    prod_crop = crop_box_2d(page_img, box)
                    prod_uri = image_to_data_uri(prod_crop)
                except Exception as exc:
                    logger.warning("Failed to crop product_box_2d on page %d: %s", page_idx, exc)

            if not prod_uri:
                continue

            all_steps.append(
                SynthesisStep(
                    step_index=step_counter,
                    reagents=str(raw_step.get("reagents") or ""),
                    conditions=str(raw_step.get("conditions") or ""),
                    yield_str=str(raw_step.get("yield") or ""),
                    named_reaction=str(raw_step.get("named_reaction") or ""),
                    product_image=prod_uri,
                    notes=str(raw_step.get("notes") or ""),
                )
            )
            step_counter += 1

    problem = SynthesisProblem(
        id=pid,
        title=title,
        target_molecule=target_molecule,
        authors=list(authors or []),
        journal=journal,
        year=year,
        doi=doi,
        pdf_url=pdf_url,
        source_url=source_url,
        start_image=start_image_uri,
        steps=all_steps,
    )
    return ExtractionResult(problem=problem, difficulty=difficulty, tags=tags)
