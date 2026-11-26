"""RDKit-based SMILES validation, canonicalization, and 2D SVG/PNG rendering."""

from __future__ import annotations

import html
from io import BytesIO
from typing import TYPE_CHECKING

try:
    from rdkit import Chem
    from rdkit.Chem import Draw, rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D

    RDKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when rdkit is absent
    Chem = None  # type: ignore[assignment]
    Draw = None  # type: ignore[assignment]
    rdDepictor = None  # type: ignore[assignment]
    rdMolDraw2D = None  # type: ignore[assignment]
    RDKIT_AVAILABLE = False

if TYPE_CHECKING:
    from synthesis_finder.models import SynthesisProblem


def _parse_mol(smiles: str):
    """Parse SMILES into an RDKit Mol with 2D coordinates, or return None."""
    if not RDKIT_AVAILABLE or not smiles or not smiles.strip():
        return None
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return None
    rdDepictor.Compute2DCoords(mol)
    return mol


def validate_smiles(smiles: str) -> bool:
    """Return True if RDKit can parse the SMILES string."""
    return _parse_mol(smiles) is not None


def canonicalize_smiles(smiles: str) -> str | None:
    """Return canonical SMILES, or None if invalid or RDKit is unavailable."""
    if not RDKIT_AVAILABLE or not smiles or not smiles.strip():
        return None
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return None
    return Chem.MolToSmiles(mol, isomericSmiles=True)


def render_placeholder_svg(label: str = "Structure unavailable", width: int = 320, height: int = 240) -> str:
    """Return a clean fallback SVG when a SMILES is missing or invalid."""
    safe_label = html.escape(label)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="#f8fafc" stroke="#cbd5e1" rx="8"/>'
        f'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '
        f'font-family="sans-serif" font-size="13" fill="#64748b">{safe_label}</text>'
        f"</svg>"
    )


def render_molecule_svg(
    smiles: str,
    *,
    width: int = 320,
    height: int = 240,
    kekulize: bool = True,
) -> str | None:
    """Render a SMILES string to a clean 2D SVG string, or None if invalid."""
    mol = _parse_mol(smiles)
    if mol is None:
        return None

    if kekulize:
        try:
            Chem.Kekulize(mol, clearAromaticFlags=True)
        except Exception:
            pass

    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = drawer.drawOptions()
    opts.clearBackground = False
    opts.bondLineWidth = 2.0
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def render_molecule_png(
    smiles: str,
    *,
    width: int = 320,
    height: int = 240,
) -> bytes | None:
    """Render a SMILES string to PNG bytes, or None if invalid."""
    mol = _parse_mol(smiles)
    if mol is None:
        return None

    if hasattr(rdMolDraw2D, "MolDraw2DCairo"):
        try:
            drawer = rdMolDraw2D.MolDraw2DCairo(width, height)
            opts = drawer.drawOptions()
            opts.bondLineWidth = 2.0
            drawer.DrawMolecule(mol)
            drawer.FinishDrawing()
            return bytes(drawer.GetDrawingText())
        except Exception:
            pass

    img = Draw.MolToImage(mol, size=(width, height))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_reaction_step_svg(
    reagents: str,
    conditions: str = "",
    yield_str: str = "",
    named_reaction: str = "",
    *,
    width: int = 260,
    height: int = 120,
) -> str:
    """Render a clean SVG reaction arrow block with reagents, conditions, and yield."""
    top_text = html.escape((reagents or "—")[:44])
    cond_parts = [p for p in (conditions, yield_str) if p]
    bottom_text = html.escape(" | ".join(cond_parts)[:44])
    tag_text = html.escape(named_reaction[:36]) if named_reaction else ""
    mid_y = height // 2

    tag_el = (
        f'<text x="50%" y="18" text-anchor="middle" font-family="sans-serif" '
        f'font-size="11" font-weight="600" fill="#0f766e">{tag_text}</text>'
        if tag_text
        else ""
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f"{tag_el}"
        f'<text x="50%" y="{mid_y - 12}" text-anchor="middle" font-family="sans-serif" '
        f'font-size="12" fill="#1e293b">{top_text}</text>'
        f'<line x1="20" y1="{mid_y}" x2="{width - 28}" y2="{mid_y}" '
        f'stroke="#334155" stroke-width="2"/>'
        f'<polygon points="{width - 28},{mid_y - 5} {width - 16},{mid_y} {width - 28},{mid_y + 5}" '
        f'fill="#334155"/>'
        f'<text x="50%" y="{mid_y + 20}" text-anchor="middle" font-family="sans-serif" '
        f'font-size="11" fill="#475569">{bottom_text}</text>'
        f"</svg>"
    )


def render_problem_structures(
    problem: SynthesisProblem,
    *,
    width: int = 320,
    height: int = 240,
) -> SynthesisProblem:
    """Canonicalize SMILES and populate start_svg and step product_svg in-place."""
    if problem.start_smiles:
        canon = canonicalize_smiles(problem.start_smiles)
        if canon:
            problem.start_smiles = canon
        svg = render_molecule_svg(problem.start_smiles, width=width, height=height)
        problem.start_svg = svg or render_placeholder_svg("Starting material", width, height)
    elif not problem.start_svg:
        problem.start_svg = render_placeholder_svg("Starting material", width, height)

    for step in problem.steps:
        if step.product_smiles:
            canon = canonicalize_smiles(step.product_smiles)
            if canon:
                step.product_smiles = canon
            svg = render_molecule_svg(step.product_smiles, width=width, height=height)
            step.product_svg = svg or render_placeholder_svg(f"Step {step.step_index}", width, height)
        elif not step.product_svg:
            step.product_svg = render_placeholder_svg(f"Step {step.step_index}", width, height)

    return problem
