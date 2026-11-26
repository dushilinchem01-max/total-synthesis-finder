"""Shared data models and JSON serialization for synthesis_finder."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SynthesisStep:
    """A single synthetic step in a total synthesis route."""

    step_index: int
    reagents: str = ""
    conditions: str = ""
    yield_str: str = ""
    named_reaction: str = ""
    product_smiles: str = ""
    product_svg: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict using 'yield' for yield_str."""
        return {
            "step_index": self.step_index,
            "reagents": self.reagents,
            "conditions": self.conditions,
            "yield": self.yield_str,
            "named_reaction": self.named_reaction,
            "product_smiles": self.product_smiles,
            "product_svg": self.product_svg,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisStep:
        """Deserialize from a dict, accepting either 'yield' or 'yield_str'."""
        yield_val = data.get("yield")
        if yield_val is None:
            yield_val = data.get("yield_str", "")
        return cls(
            step_index=int(data.get("step_index", 1)),
            reagents=str(data.get("reagents") or ""),
            conditions=str(data.get("conditions") or ""),
            yield_str=str(yield_val or ""),
            named_reaction=str(data.get("named_reaction") or ""),
            product_smiles=str(data.get("product_smiles") or ""),
            product_svg=str(data.get("product_svg") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass
class SynthesisProblem:
    """Complete extracted total synthesis problem with structures and steps."""

    id: str
    title: str
    target_molecule: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: int | None = None
    doi: str = ""
    pdf_url: str = ""
    source_url: str = ""
    start_smiles: str = ""
    start_svg: str = ""
    steps: list[SynthesisStep] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize problem and all steps to a JSON-compatible dict."""
        return {
            "id": self.id,
            "title": self.title,
            "target_molecule": self.target_molecule,
            "authors": list(self.authors),
            "journal": self.journal,
            "year": self.year,
            "doi": self.doi,
            "pdf_url": self.pdf_url,
            "source_url": self.source_url,
            "start_smiles": self.start_smiles,
            "start_svg": self.start_svg,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize problem to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisProblem:
        """Deserialize problem from a dict."""
        raw_steps = data.get("steps") or []
        steps = [
            s if isinstance(s, SynthesisStep) else SynthesisStep.from_dict(s)
            for s in raw_steps
        ]
        year_raw = data.get("year")
        year = int(year_raw) if year_raw is not None and str(year_raw).strip() else None
        authors_raw = data.get("authors") or []
        if isinstance(authors_raw, str):
            authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
        else:
            authors = [str(a) for a in authors_raw]
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            target_molecule=str(data.get("target_molecule") or ""),
            authors=authors,
            journal=str(data.get("journal") or ""),
            year=year,
            doi=str(data.get("doi") or ""),
            pdf_url=str(data.get("pdf_url") or ""),
            source_url=str(data.get("source_url") or ""),
            start_smiles=str(data.get("start_smiles") or ""),
            start_svg=str(data.get("start_svg") or ""),
            steps=steps,
            created_at=str(data.get("created_at") or now_iso()),
        )

    @classmethod
    def from_json(cls, raw: str) -> SynthesisProblem:
        """Deserialize problem from a JSON string."""
        return cls.from_dict(json.loads(raw))


@dataclass
class CatalogEntry:
    """Summary entry stored in site/data/catalog.json for the web UI."""

    id: str
    title: str
    target_molecule: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: int | None = None
    doi: str = ""
    pdf_url: str = ""
    source_url: str = ""
    num_steps: int = 0
    difficulty: str = "intermediate"
    tags: list[str] = field(default_factory=list)
    problem_file: str = ""
    html_file: str = ""
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize catalog entry to a JSON-compatible dict."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize catalog entry to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CatalogEntry:
        """Deserialize catalog entry from a dict."""
        year_raw = data.get("year")
        year = int(year_raw) if year_raw is not None and str(year_raw).strip() else None
        authors_raw = data.get("authors") or []
        if isinstance(authors_raw, str):
            authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
        else:
            authors = [str(a) for a in authors_raw]
        tags_raw = data.get("tags") or []
        tags = [str(t) for t in tags_raw]
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            target_molecule=str(data.get("target_molecule") or ""),
            authors=authors,
            journal=str(data.get("journal") or ""),
            year=year,
            doi=str(data.get("doi") or ""),
            pdf_url=str(data.get("pdf_url") or ""),
            source_url=str(data.get("source_url") or ""),
            num_steps=int(data.get("num_steps") or 0),
            difficulty=str(data.get("difficulty") or "intermediate"),
            tags=tags,
            problem_file=str(data.get("problem_file") or ""),
            html_file=str(data.get("html_file") or ""),
            created_at=str(data.get("created_at") or now_iso()),
        )

    @classmethod
    def from_problem(
        cls,
        problem: SynthesisProblem,
        *,
        difficulty: str = "intermediate",
        tags: list[str] | None = None,
        problem_file: str = "",
        html_file: str = "",
    ) -> CatalogEntry:
        """Create a CatalogEntry from a SynthesisProblem."""
        return cls(
            id=problem.id,
            title=problem.title,
            target_molecule=problem.target_molecule,
            authors=list(problem.authors),
            journal=problem.journal,
            year=problem.year,
            doi=problem.doi,
            pdf_url=problem.pdf_url,
            source_url=problem.source_url,
            num_steps=len(problem.steps),
            difficulty=difficulty,
            tags=list(tags or []),
            problem_file=problem_file or f"problems/{problem.id}.json",
            html_file=html_file or f"problems/{problem.id}.html",
            created_at=problem.created_at,
        )
