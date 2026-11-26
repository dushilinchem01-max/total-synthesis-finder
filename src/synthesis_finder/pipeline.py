"""End-to-end CLI pipeline: fetch ChemASAP -> filter -> resolve OA PDF -> extract -> build."""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from pathlib import Path
from typing import Sequence

from synthesis_finder.article_filter import heuristic_filter
from synthesis_finder.chemasap_client import ChemASAPClient, RawArticle
from synthesis_finder.extractor import extract_synthesis_from_pdf, is_total_synthesis_candidate
from synthesis_finder.llm_clients import MultiProviderLLM
from synthesis_finder.models import CatalogEntry, now_iso
from synthesis_finder.oa_resolver import OAResolver, normalize_doi
from synthesis_finder.snake_builder import save_snake_html

logger = logging.getLogger(__name__)


def _parse_year(published_at: str) -> int | None:
    if not published_at:
        return None
    for token in published_at.split("-"):
        if len(token) == 4 and token.isdigit():
            return int(token)
    return None


def _split_authors(authors_str: str) -> list[str]:
    if not authors_str:
        return []
    return [a.strip() for a in authors_str.split(",") if a.strip()]


def load_catalog(catalog_path: Path) -> tuple[list[dict], set[str]]:
    """Load existing catalog entries and return (entries_list, known_dois)."""
    if not catalog_path.exists():
        return [], set()
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        entries = list(data.get("problems") or [])
        known_dois = {
            normalize_doi(e.get("doi"))
            for e in entries
            if e.get("doi")
        }
        return entries, known_dois
    except Exception as exc:
        logger.warning("Failed to load existing catalog %s: %s", catalog_path, exc)
        return [], set()


def save_catalog(catalog_path: Path, entries: list[dict]) -> None:
    """Write catalog.json atomically."""
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": now_iso(),
        "problems": entries,
    }
    catalog_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def run_pipeline(
    *,
    out_dir: str | Path = "site/data",
    max_articles: int = 5,
    feed_limit: int = 100,
    journals: Sequence[str] | None = None,
    use_llm_screening: bool = True,
) -> list[CatalogEntry]:
    """Run one full ingestion + extraction + build cycle."""
    out_path = Path(out_dir)
    problems_dir = out_path / "problems"
    problems_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = out_path / "catalog.json"

    existing_entries, known_dois = load_catalog(catalog_path)

    llm = MultiProviderLLM()
    has_text_llm = llm.groq.is_configured or llm.nvidia.is_configured or llm.gemini.is_configured
    if not has_text_llm:
        logger.warning("No LLM API keys configured (GEMINI_API_KEY / GROQ_API_KEY / NVIDIA_API_KEY). Exiting cleanly.")
        return []

    with ChemASAPClient() as chemasap:
        articles: list[RawArticle] = chemasap.fetch_latest_articles(
            journals=journals,
            limit=feed_limit,
        )

    logger.info("Fetched %d articles from ChemASAP", len(articles))

    new_entries: list[CatalogEntry] = []
    processed_count = 0

    with OAResolver() as oa_resolver, tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        for article in articles:
            if processed_count >= max_articles:
                break

            doi_norm = normalize_doi(article.doi)
            if doi_norm and doi_norm in known_dois:
                continue

            h_res = heuristic_filter(article.title, article.abstract)
            if not h_res.passed:
                continue

            if use_llm_screening and has_text_llm:
                try:
                    if not is_total_synthesis_candidate(article.title, article.abstract, llm=llm):
                        logger.info("LLM screening rejected: %s", article.title)
                        continue
                except Exception as exc:
                    logger.warning("LLM screening failed for %s: %s", article.title, exc)

            oa_res = oa_resolver.resolve(doi=doi_norm, url=article.url, oa_hint=article.oa)
            if not oa_res.is_oa or not oa_res.pdf_url:
                logger.info("No open-access PDF for %s (%s)", article.title, doi_norm)
                continue

            if not llm.gemini.is_configured:
                logger.warning("GEMINI_API_KEY is required for multimodal PDF extraction; skipping %s", article.title)
                continue

            pdf_file = tmp_path / f"article_{processed_count}.pdf"
            try:
                oa_resolver.download_pdf(oa_res.pdf_url, pdf_file)
                extraction = extract_synthesis_from_pdf(
                    pdf_path=pdf_file,
                    title=article.title,
                    authors=_split_authors(article.authors),
                    journal=article.journal,
                    year=_parse_year(article.published_at),
                    doi=doi_norm,
                    pdf_url=oa_res.pdf_url,
                    source_url=article.url,
                    llm=llm,
                    render_svgs=True,
                )
            except Exception as exc:
                logger.warning("Extraction failed for %s: %s", article.title, exc)
                continue

            problem = extraction.problem
            if not problem.steps:
                logger.info("No synthesis steps extracted for %s; skipping", article.title)
                continue

            json_rel = f"problems/{problem.id}.json"
            html_rel = f"problems/{problem.id}.html"
            (out_path / json_rel).write_text(problem.to_json(), encoding="utf-8")
            save_snake_html(problem, out_path / html_rel)

            entry = CatalogEntry.from_problem(
                problem,
                difficulty=extraction.difficulty,
                tags=extraction.tags,
                problem_file=json_rel,
                html_file=html_rel,
            )
            new_entries.append(entry)
            if doi_norm:
                known_dois.add(doi_norm)
            processed_count += 1
            logger.info("Added synthesis problem: %s (%d steps)", entry.target_molecule, entry.num_steps)

    if new_entries:
        merged = [e.to_dict() for e in new_entries] + existing_entries
        save_catalog(catalog_path, merged)
        logger.info("Updated catalog with %d new problem(s)", len(new_entries))
    else:
        logger.info("No new problems added.")

    return new_entries


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for synthesis-finder."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Fetch, extract, and build total synthesis problems.")
    parser.add_argument("--max-articles", type=int, default=5, help="Max new problems to extract per run")
    parser.add_argument("--feed-limit", type=int, default=100, help="Number of recent ChemASAP articles to scan")
    parser.add_argument("--out-dir", type=str, default="site/data", help="Output data directory")
    parser.add_argument("--no-llm-screen", action="store_true", help="Skip LLM screening step")
    args = parser.parse_args(argv)

    run_pipeline(
        out_dir=args.out_dir,
        max_articles=args.max_articles,
        feed_limit=args.feed_limit,
        use_llm_screening=not args.no_llm_screen,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
