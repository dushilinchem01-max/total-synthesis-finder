"""Self-contained offline HTML flashcard generator (snake layout) adapted from cbd2."""

from __future__ import annotations

import html
from pathlib import Path

from synthesis_finder.chem_render import render_molecule_svg, render_placeholder_svg
from synthesis_finder.models import SynthesisProblem, SynthesisStep

STEPS_PER_ROW = 4


def _ensure_svg(svg: str, smiles: str, label: str) -> str:
    """Return an inline SVG string, rendering from SMILES or falling back to a placeholder."""
    if svg and "<svg" in svg:
        return svg
    if smiles:
        rendered = render_molecule_svg(smiles, width=280, height=200)
        if rendered:
            return rendered
    return render_placeholder_svg(label, width=280, height=200)


def _format_step_arrow(step: SynthesisStep, direction: str) -> str:
    """Render an HTML reaction arrow block with toggleable reagents/conditions."""
    reagents = html.escape(step.reagents or "—")
    cond_parts = [p for p in (step.conditions, step.yield_str) if p]
    conditions = html.escape(" · ".join(cond_parts)) if cond_parts else ""
    named = html.escape(step.named_reaction) if step.named_reaction else ""
    notes = html.escape(step.notes) if step.notes else ""

    arrow_glyph = "&#8594;" if direction == "ltr" else "&#8592;"
    title_attr = f' title="{notes}"' if notes else ""

    return f"""
    <div class="step-arrow" data-step="{step.step_index}"{title_attr}>
      <div class="reagent-box" onclick="toggleReveal(this)" tabindex="0" role="button" aria-label="Toggle step {step.step_index} reagents">
        <span class="step-badge">Step {step.step_index}</span>
        {f'<div class="named-rxn">{named}</div>' if named else ''}
        <div class="reagents-text">{reagents}</div>
        {f'<div class="cond-text">{conditions}</div>' if conditions else ''}
      </div>
      <div class="arrow-line">{arrow_glyph}</div>
    </div>
    """


def _format_mol_card(svg: str, label: str, *, is_start: bool = False, step_index: int = 0) -> str:
    """Render a molecule structure card (start material or step product)."""
    cls = "mol-card start-card" if is_start else "mol-card product-card"
    click_attr = "" if is_start else ' onclick="toggleReveal(this)" tabindex="0" role="button"'
    badge = "Starting Material" if is_start else f"Intermediate {step_index}"
    return f"""
    <div class="{cls}"{click_attr}>
      <div class="mol-badge">{html.escape(badge)}</div>
      <div class="mol-svg">{svg}</div>
    </div>
    """


def build_snake_html(problem: SynthesisProblem) -> str:
    """Generate a self-contained offline HTML snake-layout flashcard for a SynthesisProblem."""
    title = html.escape(problem.title or problem.target_molecule or "Total Synthesis")
    target = html.escape(problem.target_molecule or "Target Molecule")
    journal = html.escape(problem.journal or "")
    year = str(problem.year) if problem.year else ""
    authors = html.escape(", ".join(problem.authors[:4]) + (" et al." if len(problem.authors) > 4 else ""))
    doi_url = f"https://doi.org/{html.escape(problem.doi)}" if problem.doi else ""
    pdf_url = html.escape(problem.pdf_url) if problem.pdf_url else ""

    start_svg = _ensure_svg(problem.start_svg, problem.start_smiles, "Starting Material")

    # Build linear sequence of nodes: [start_card, (step_arrow, product_card), ...]
    # Chunk into rows of STEPS_PER_ROW steps in serpentine (snake) order.
    rows_html: list[str] = []
    steps = problem.steps
    if not steps:
        rows_html.append(
            f'<div class="snake-row ltr">{_format_mol_card(start_svg, "Start", is_start=True)}</div>'
        )
    else:
        num_rows = (len(steps) + STEPS_PER_ROW - 1) // STEPS_PER_ROW
        for r_idx in range(num_rows):
            chunk = steps[r_idx * STEPS_PER_ROW : (r_idx + 1) * STEPS_PER_ROW]
            direction = "ltr" if r_idx % 2 == 0 else "rtl"
            items: list[str] = []

            if r_idx == 0:
                items.append(_format_mol_card(start_svg, "Start", is_start=True))

            for step in chunk:
                prod_svg = _ensure_svg(
                    step.product_svg,
                    step.product_smiles,
                    f"Step {step.step_index} Product",
                )
                items.append(_format_step_arrow(step, direction))
                items.append(
                    _format_mol_card(
                        prod_svg,
                        f"Step {step.step_index}",
                        is_start=False,
                        step_index=step.step_index,
                    )
                )

            if direction == "rtl":
                items.reverse()

            rows_html.append(f'<div class="snake-row {direction}">{"".join(items)}</div>')
            if r_idx < num_rows - 1:
                turn_side = "turn-right" if direction == "ltr" else "turn-left"
                rows_html.append(f'<div class="snake-turn {turn_side}">&#8595;</div>')

    meta_parts = [p for p in (authors, journal, year) if p]
    meta_line = " &middot; ".join(meta_parts)

    links_html = ""
    if doi_url:
        links_html += f'<a class="btn-link" href="{doi_url}" target="_blank" rel="noopener">DOI</a>'
    if pdf_url:
        links_html += f'<a class="btn-link" href="{pdf_url}" target="_blank" rel="noopener">PDF</a>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{target} — Total Synthesis Flashcard</title>
<style>
  :root {{
    --bg: #f8fafc;
    --card: #ffffff;
    --border: #cbd5e1;
    --text: #0f172a;
    --muted: #475569;
    --accent: #1d4ed8;
    --accent-soft: #eff6ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.4;
  }}
  header {{
    position: sticky;
    top: 0;
    z-index: 20;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    padding: 12px 20px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }}
  .title-block h1 {{
    margin: 0;
    font-size: 1.15rem;
  }}
  .title-block .meta {{
    font-size: 0.85rem;
    color: var(--muted);
    margin-top: 2px;
  }}
  .controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }}
  button, .btn-link {{
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--text);
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    cursor: pointer;
    text-decoration: none;
    font-weight: 500;
  }}
  button:hover, .btn-link:hover {{
    border-color: var(--accent);
    color: var(--accent);
  }}
  button.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}
  main {{
    max-width: 1440px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }}
  .snake-board {{
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}
  .snake-row {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
  }}
  .snake-row.rtl {{
    justify-content: flex-end;
  }}
  .snake-turn {{
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--accent);
    padding: 0 48px;
  }}
  .snake-turn.turn-right {{ text-align: right; }}
  .snake-turn.turn-left {{ text-align: left; }}
  .mol-card {{
    position: relative;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: #fff;
    padding: 8px;
    min-width: 200px;
    transition: box-shadow 0.15s;
  }}
  .product-card {{
    cursor: pointer;
  }}
  .product-card:hover {{
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
  }}
  .mol-badge {{
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--muted);
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  .start-card .mol-badge {{
    color: var(--accent);
  }}
  .mol-svg svg {{
    display: block;
    max-width: 240px;
    height: auto;
  }}
  .step-arrow {{
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 160px;
    max-width: 220px;
    text-align: center;
  }}
  .reagent-box {{
    background: var(--accent-soft);
    border: 1px solid #bfdbfe;
    border-radius: 6px;
    padding: 6px 10px;
    cursor: pointer;
    width: 100%;
    font-size: 0.8rem;
  }}
  .step-badge {{
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 2px;
  }}
  .named-rxn {{
    font-weight: 600;
    color: #1e3a8a;
    font-size: 0.75rem;
  }}
  .reagents-text {{
    font-weight: 600;
    color: var(--text);
  }}
  .cond-text {{
    color: var(--muted);
    font-size: 0.74rem;
    margin-top: 2px;
  }}
  .arrow-line {{
    font-size: 1.5rem;
    color: var(--text);
    line-height: 1;
    margin-top: 4px;
  }}
  .is-hidden .mol-svg,
  .is-hidden .named-rxn,
  .is-hidden .reagents-text,
  .is-hidden .cond-text {{
    filter: blur(8px);
    opacity: 0.15;
    user-select: none;
  }}
  .is-hidden::after {{
    content: "Click to reveal";
    display: block;
    font-size: 0.72rem;
    color: var(--accent);
    font-weight: 600;
    margin-top: 4px;
  }}
  @media print {{
    header .controls {{ display: none; }}
    .is-hidden .mol-svg,
    .is-hidden .named-rxn,
    .is-hidden .reagents-text,
    .is-hidden .cond-text {{
      filter: none;
      opacity: 1;
    }}
    .is-hidden::after {{ display: none; }}
  }}
</style>
</head>
<body>
<header>
  <div class="title-block">
    <h1>{title}</h1>
    <div class="meta">{meta_line}</div>
  </div>
  <div class="controls">
    <button type="button" id="btnHideReagents" onclick="toggleGroup('reagent-box', this)">Hide Reagents</button>
    <button type="button" id="btnHideProducts" onclick="toggleGroup('product-card', this)">Hide Products</button>
    <button type="button" onclick="revealAll()">Reveal All</button>
    <button type="button" onclick="window.print()">Print / PDF</button>
    {links_html}
  </div>
</header>
<main>
  <div class="snake-board">
    {"".join(rows_html)}
  </div>
</main>
<script>
  function toggleReveal(el) {{
    el.classList.toggle('is-hidden');
  }}
  function toggleGroup(cls, btn) {{
    const active = btn.classList.toggle('active');
    document.querySelectorAll('.' + cls).forEach(el => {{
      el.classList.toggle('is-hidden', active);
    }});
  }}
  function revealAll() {{
    document.querySelectorAll('.is-hidden').forEach(el => el.classList.remove('is-hidden'));
    document.querySelectorAll('.controls button.active').forEach(b => b.classList.remove('active'));
  }}
</script>
</body>
</html>
"""


def save_snake_html(problem: SynthesisProblem, dest_path: str | Path) -> Path:
    """Render and write a snake-layout HTML flashcard to disk."""
    path = Path(dest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_snake_html(problem), encoding="utf-8")
    return path
