"""Unit tests for snake_builder and pipeline orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from synthesis_finder.chemasap_client import RawArticle
from synthesis_finder.extractor import ExtractionResult
from synthesis_finder.models import SynthesisProblem, SynthesisStep
from synthesis_finder.oa_resolver import OAResolution
from synthesis_finder.pipeline import run_pipeline
from synthesis_finder.snake_builder import build_snake_html, save_snake_html


def _sample_problem() -> SynthesisProblem:
    return SynthesisProblem(
        id="demo-strychnine-1234",
        title="Total Synthesis of (-)-Strychnine",
        target_molecule="(-)-Strychnine",
        authors=["C. D. Vanderwal", "D. B. C. Martin"],
        journal="Chem. Sci.",
        year=2011,
        doi="10.1039/c1sc00100a",
        pdf_url="https://example.com/strychnine.pdf",
        source_url="https://example.com/strychnine",
        start_smiles="c1ccccc1",
        steps=[
            SynthesisStep(
                step_index=1,
                reagents="LDA, THF",
                conditions="-78 °C, 2 h",
                yield_str="85%",
                named_reaction="Aldol reaction",
                product_smiles="CC(=O)c1ccccc1",
                notes="High diastereoselectivity",
            ),
            SynthesisStep(
                step_index=2,
                reagents="NaBH4, MeOH",
                conditions="0 °C, 1 h",
                yield_str="92%",
                named_reaction="Reduction",
                product_smiles="CC(O)c1ccccc1",
            ),
        ],
    )


def test_build_and_save_snake_html(tmp_path: Path) -> None:
    problem = _sample_problem()
    html_text = build_snake_html(problem)
    assert "Total Synthesis of (-)-Strychnine" in html_text
    assert "Hide Reagents" in html_text
    assert "Hide Products" in html_text
    assert "LDA, THF" in html_text
    assert "Aldol reaction" in html_text

    out_file = save_snake_html(problem, tmp_path / "problems" / f"{problem.id}.html")
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == html_text


def test_run_pipeline_end_to_end_and_dedup(tmp_path: Path) -> None:
    out_dir = tmp_path / "data"
    sample_prob = _sample_problem()

    raw_article = RawArticle(
        id="art-1",
        title="Total Synthesis of (-)-Strychnine",
        authors="C. D. Vanderwal, D. B. C. Martin",
        journal="Chem. Sci.",
        journal_id="chemsci",
        journal_abbr="Chem. Sci.",
        doi="10.1039/c1sc00100a",
        abstract="We report a concise total synthesis of strychnine.",
        url="https://example.com/strychnine",
        toc_image_url=None,
        published_at="2026-11-20",
        source_type="journal",
        oa=True,
    )

    mock_llm = MagicMock()
    mock_llm.groq.is_configured = True
    mock_llm.nvidia.is_configured = False
    mock_llm.gemini.is_configured = True

    with (
        patch("synthesis_finder.pipeline.MultiProviderLLM", return_value=mock_llm),
        patch("synthesis_finder.pipeline.ChemASAPClient") as mock_client_cls,
        patch("synthesis_finder.pipeline.OAResolver") as mock_oa_cls,
        patch("synthesis_finder.pipeline.is_total_synthesis_candidate", return_value=True),
        patch(
            "synthesis_finder.pipeline.extract_synthesis_from_pdf",
            return_value=ExtractionResult(problem=sample_prob, difficulty="advanced", tags=["alkaloid"]),
        ),
    ):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.fetch_latest_articles.return_value = [raw_article]

        mock_oa = mock_oa_cls.return_value.__enter__.return_value
        mock_oa.resolve.return_value = OAResolution(
            doi="10.1039/c1sc00100a",
            pdf_url="https://example.com/strychnine.pdf",
            source="unpaywall",
            is_oa=True,
        )
        mock_oa.download_pdf.side_effect = lambda url, dest: Path(dest).write_bytes(b"%PDF-1.4 demo")

        added = run_pipeline(out_dir=out_dir, max_articles=5)
        assert len(added) == 1
        assert (out_dir / "catalog.json").exists()
        assert (out_dir / "problems" / f"{sample_prob.id}.json").exists()
        assert (out_dir / "problems" / f"{sample_prob.id}.html").exists()

        catalog = json.loads((out_dir / "catalog.json").read_text(encoding="utf-8"))
        assert len(catalog["problems"]) == 1
        assert catalog["problems"][0]["doi"] == "10.1039/c1sc00100a"

        # Second run should deduplicate by DOI and add 0 new problems
        added_again = run_pipeline(out_dir=out_dir, max_articles=5)
        assert len(added_again) == 0
