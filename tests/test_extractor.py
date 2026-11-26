"""Unit tests for models, llm_clients, chem_render, and extractor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synthesis_finder.chem_render import (
    RDKIT_AVAILABLE,
    canonicalize_smiles,
    render_molecule_png,
    render_molecule_svg,
    render_problem_structures,
    render_reaction_step_svg,
    validate_smiles,
)
from synthesis_finder.extractor import (
    create_problem_id,
    extract_synthesis_from_pdf,
    is_total_synthesis_candidate,
    screen_article,
)
from synthesis_finder.llm_clients import (
    Attachment,
    GeminiClient,
    LLMError,
    MultiProviderLLM,
    create_groq_client,
    create_nvidia_client,
    extract_json_from_text,
)
from synthesis_finder.models import CatalogEntry, SynthesisProblem, SynthesisStep


def test_models_roundtrip_and_yield_alias() -> None:
    step = SynthesisStep(
        step_index=1,
        reagents="Pd(PPh3)4, K2CO3",
        conditions="THF/H2O, 80 C",
        yield_str="88%",
        named_reaction="Suzuki-Miyaura coupling",
        product_smiles="c1ccccc1-c2ccccc2",
        notes="Clean cross-coupling",
    )
    step_dict = step.to_dict()
    assert step_dict["yield"] == "88%"
    assert "yield_str" not in step_dict

    restored_step = SynthesisStep.from_dict({"step_index": 1, "yield": "88%", "reagents": "Pd"})
    assert restored_step.yield_str == "88%"

    problem = SynthesisProblem(
        id="test-prob-1",
        title="Total Synthesis of Molecule X",
        target_molecule="Molecule X",
        authors=["A. Chemist", "B. Researcher"],
        journal="J. Am. Chem. Soc.",
        year=2026,
        doi="10.1021/jacs.0001",
        start_smiles="Brc1ccccc1",
        steps=[step],
    )
    raw_json = problem.to_json()
    reloaded = SynthesisProblem.from_json(raw_json)
    assert reloaded.id == "test-prob-1"
    assert reloaded.year == 2026
    assert reloaded.steps[0].yield_str == "88%"

    entry = CatalogEntry.from_problem(reloaded, difficulty="advanced", tags=["alkaloid"])
    entry_dict = entry.to_dict()
    assert entry_dict["num_steps"] == 1
    assert entry_dict["difficulty"] == "advanced"
    assert entry_dict["problem_file"] == "problems/test-prob-1.json"
    assert entry_dict["html_file"] == "problems/test-prob-1.html"
    assert CatalogEntry.from_dict(entry_dict).tags == ["alkaloid"]


def test_extract_json_from_text() -> None:
    fenced = 'Here is the result:\n```json\n{"is_candidate": true, "reason": "ok"}\n```'
    assert extract_json_from_text(fenced) == {"is_candidate": True, "reason": "ok"}

    embedded = 'Result: {"a": 1, "b": [2, 3]} trailing text'
    assert extract_json_from_text(embedded) == {"a": 1, "b": [2, 3]}


def test_llm_clients_multimodal_and_fallback() -> None:
    seen_urls: list[str] = []

    def groq_fail_transport(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(429, json={"error": "rate limited"})

    def nvidia_ok_transport(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"is_candidate": true, "reason": "total synthesis"}'}}]},
        )

    def gemini_ok_transport(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        body = json.loads(request.content.decode("utf-8"))
        parts = body["contents"][0]["parts"]
        assert parts[0]["inline_data"]["mime_type"] == "application/pdf"
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
        )

    groq = create_groq_client(
        api_key="g-key",
        http_client=httpx.Client(transport=httpx.MockTransport(groq_fail_transport)),
    )
    nvidia = create_nvidia_client(
        api_key="n-key",
        http_client=httpx.Client(transport=httpx.MockTransport(nvidia_ok_transport)),
    )
    gemini = GeminiClient(
        api_key="gem-key",
        http_client=httpx.Client(transport=httpx.MockTransport(gemini_ok_transport)),
    )
    llm = MultiProviderLLM(gemini=gemini, groq=groq, nvidia=nvidia)

    text_resp = llm.generate_text("Screen this", json_mode=True)
    assert '"is_candidate": true' in text_resp
    assert any("groq.com" in u for u in seen_urls)
    assert any("nvidia.com" in u for u in seen_urls)

    mm_resp = llm.generate_multimodal("Extract", [Attachment(b"%PDF-1.4", "application/pdf")], json_mode=True)
    assert mm_resp == '{"ok": true}'
    assert any("generativelanguage.googleapis.com" in u for u in seen_urls)


def test_llm_unconfigured_raises() -> None:
    llm = MultiProviderLLM(
        gemini=GeminiClient(api_key=""),
        groq=create_groq_client(api_key=""),
        nvidia=create_nvidia_client(api_key=""),
    )
    with pytest.raises(LLMError):
        llm.generate_text("hello")


@pytest.mark.skipif(not RDKIT_AVAILABLE, reason="RDKit not installed")
def test_chem_render_rdkit() -> None:
    assert validate_smiles("CCO")
    assert not validate_smiles("not_a_smiles_123")
    assert canonicalize_smiles("C(C)O") == "CCO"
    assert canonicalize_smiles("invalid") is None

    svg = render_molecule_svg("c1ccccc1")
    assert svg is not None
    assert "<svg" in svg

    png = render_molecule_png("c1ccccc1")
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    arrow_svg = render_reaction_step_svg("NaBH4", "MeOH, 0 C", "94%", "Reduction")
    assert "<svg" in arrow_svg
    assert "NaBH4" in arrow_svg

    problem = SynthesisProblem(
        id="p1",
        title="Test",
        start_smiles="C(=O)C",
        steps=[
            SynthesisStep(step_index=1, product_smiles="CCO"),
            SynthesisStep(step_index=2, product_smiles="INVALID_SMILES"),
        ],
    )
    render_problem_structures(problem)
    assert problem.start_smiles == "CC=O"
    assert "<svg" in problem.start_svg
    assert "<svg" in problem.steps[0].product_svg
    assert "Step 2" in problem.steps[1].product_svg


def test_extractor_screening_and_pdf_extraction() -> None:
    def groq_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "is_candidate": True,
                                    "target_molecule": "Strychnine",
                                    "reason": "Reports an asymmetric total synthesis.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    extraction_payload = {
        "target_molecule": "Aspirin Analogue",
        "start_smiles": "Oc1ccccc1C(=O)O",
        "difficulty": "introductory",
        "tags": ["esterification", "total synthesis"],
        "steps": [
            {
                "step_index": 1,
                "reagents": "Ac2O, H2SO4",
                "conditions": "60 C, 1 h",
                "yield": "91%",
                "named_reaction": "O-Acylation",
                "product_smiles": "CC(=O)Oc1ccccc1C(=O)O",
                "notes": "Selective phenolic acylation",
            }
        ],
    }

    def gemini_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(extraction_payload)}]}}
                ]
            },
        )

    llm = MultiProviderLLM(
        groq=create_groq_client(
            api_key="g-key",
            http_client=httpx.Client(transport=httpx.MockTransport(groq_transport)),
        ),
        nvidia=create_nvidia_client(api_key=""),
        gemini=GeminiClient(
            api_key="gem-key",
            http_client=httpx.Client(transport=httpx.MockTransport(gemini_transport)),
        ),
    )

    assert is_total_synthesis_candidate("Total Synthesis of Strychnine", "We report...", llm=llm)
    screening = screen_article("Total Synthesis of Strychnine", "We report...", llm=llm)
    assert screening.target_molecule == "Strychnine"

    result = extract_synthesis_from_pdf(
        pdf_bytes=b"%PDF-1.4 dummy",
        title="Concise Synthesis of Aspirin Analogue",
        authors=["E. Fischer"],
        journal="ChemRxiv",
        year=2026,
        doi="10.26434/chemrxiv-2026-001",
        llm=llm,
    )
    assert result.difficulty == "introductory"
    assert result.tags == ["esterification", "total synthesis"]
    assert result.problem.id == create_problem_id(doi="10.26434/chemrxiv-2026-001")
    assert result.problem.target_molecule == "Aspirin Analogue"
    assert len(result.problem.steps) == 1
    assert result.problem.steps[0].yield_str == "91%"
    if RDKIT_AVAILABLE:
        assert "<svg" in result.problem.start_svg
        assert "<svg" in result.problem.steps[0].product_svg


def test_pdf_cropper_and_two_pass_extraction(tmp_path) -> None:
    import pymupdf as fitz

    from synthesis_finder.pdf_cropper import crop_box_2d, render_pdf_pages

    pdf_file = tmp_path / "demo_synth.pdf"
    doc = fitz.open()
    doc.new_page(width=600, height=800)
    p1 = doc.new_page(width=600, height=800)
    p1.draw_rect(fitz.Rect(60, 100, 180, 220), color=(0, 0, 0), fill=(0.1, 0.1, 0.1))
    p1.draw_rect(fitz.Rect(350, 100, 500, 220), color=(0, 0, 0), fill=(0.1, 0.1, 0.1))
    doc.save(str(pdf_file))
    doc.close()

    pages = render_pdf_pages(pdf_path=pdf_file, dpi=144)
    assert len(pages) == 2
    cropped = crop_box_2d(pages[1], [120, 95, 280, 305])
    assert cropped.width > 20 and cropped.height > 20

    call_count = {"n": 0}

    def gemini_two_pass(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            payload = {
                "target_molecule": "Demo Natural Product",
                "difficulty": "intermediate",
                "tags": ["total synthesis"],
                "scheme_pages": [1],
            }
        else:
            payload = {
                "start_box_2d": [120, 95, 280, 305],
                "steps": [
                    {
                        "step_index": 1,
                        "reagents": "LiAlH4",
                        "conditions": "THF, 0 °C",
                        "yield": "90%",
                        "named_reaction": "Reduction",
                        "product_box_2d": [120, 580, 280, 840],
                        "notes": "Clean conversion",
                    }
                ],
            }
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
        )

    llm = MultiProviderLLM(
        gemini=GeminiClient(
            api_key="gem-key",
            http_client=httpx.Client(transport=httpx.MockTransport(gemini_two_pass)),
        ),
        groq=create_groq_client(api_key=""),
        nvidia=create_nvidia_client(api_key=""),
    )
    res = extract_synthesis_from_pdf(pdf_path=pdf_file, title="Demo", llm=llm, dpi=144)
    assert res.problem.start_image.startswith("data:image/png;base64,")
    assert len(res.problem.steps) == 1
    assert res.problem.steps[0].product_image.startswith("data:image/png;base64,")
    assert res.problem.steps[0].reagents == "LiAlH4"

