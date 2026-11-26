"""End-to-end CLI pipeline: fetch OpenAlex + ChemASAP -> filter -> resolve OA PDF -> extract -> build."""

from __future__ import annotations

import argparse
from datetime import date
import json
import logging
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from synthesis_finder.article_filter import heuristic_filter
from synthesis_finder.chemasap_client import ChemASAPClient, RawArticle
from synthesis_finder.extractor import extract_synthesis_from_pdf, is_total_synthesis_candidate
from synthesis_finder.llm_clients import MultiProviderLLM
from synthesis_finder.models import CatalogEntry, now_iso
from synthesis_finder.oa_resolver import OAResolver, normalize_doi
from synthesis_finder.openalex_client import OpenAlexClient, resolve_date_window
from synthesis_finder.snake_builder import save_snake_html

logger = logging.getLogger(__name__)


def _parse_year(published_at: str) -> int | None:
    if not published_at:
        return None
    for token in published_at.split("-"):
        if len(token) == 4 and token.isdigit():
            return int(token)
    return None


def _parse_pub_date(published_at: str) -> date | None:
    if not published_at:
        return None
    raw = published_at.strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _within_date_range(published_at: str, date_from: str, date_to: str) -> bool:
    pub_dt = _parse_pub_date(published_at)
    if pub_dt is None:
        return True
    try:
        start_dt = date.fromisoformat(date_from)
        end_dt = date.fromisoformat(date_to)
    except ValueError:
        return True
    return start_dt <= pub_dt <= end_dt


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


def save_catalog(catalog_path: Path, entries: list[dict], *, extra_meta: dict | None = None) -> None:
    """Write catalog.json atomically."""
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "updated_at": now_iso(),
        "problems": entries,
    }
    if extra_meta:
        payload.update(extra_meta)
    catalog_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def delete_problems(
    out_dir: str | Path = "site/data",
    problem_ids: Sequence[str] | None = None,
    *,
    delete_all: bool = False,
) -> list[str]:
    """Delete specified synthesis problems (or all) from catalog.json and disk."""
    out_path = Path(out_dir)
    catalog_path = out_path / "catalog.json"
    problems_dir = out_path / "problems"

    existing_entries, _ = load_catalog(catalog_path)
    target_set = {pid.strip() for pid in (problem_ids or ()) if pid and pid.strip()}

    removed_ids: list[str] = []
    remaining: list[dict] = []

    for entry in existing_entries:
        pid = str(entry.get("id") or "")
        should_remove = delete_all or (pid in target_set)
        if should_remove:
            removed_ids.append(pid)
            for rel_key in ("problem_file", "html_file"):
                rel = entry.get(rel_key)
                if rel:
                    fpath = out_path / str(rel)
                    if fpath.exists():
                        fpath.unlink()
            for ext in (".json", ".html"):
                fallback_file = problems_dir / f"{pid}{ext}"
                if fallback_file.exists():
                    fallback_file.unlink()
        else:
            remaining.append(entry)

    if delete_all and problems_dir.exists():
        for leftover in problems_dir.iterdir():
            if leftover.is_file() and leftover.suffix in {".json", ".html"}:
                leftover.unlink()

    save_catalog(catalog_path, remaining)
    logger.info("Deleted %d synthesis problem(s): %s", len(removed_ids), removed_ids)
    return removed_ids


def _emit(cb: Callable[[str], None] | None, msg: str) -> None:
    logger.info("%s", msg)
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


def _download_article_pdf(
    article: RawArticle,
    doi_norm: str,
    oa_resolver: OAResolver,
    pdf_file: Path,
) -> str | None:
    """Try candidate PDF URLs first, then OAResolver fallback; return downloaded PDF URL or None."""
    tried: set[str] = set()

    for cand_url in article.candidate_pdf_urls:
        url = (cand_url or "").strip()
        if not url or url in tried:
            continue
        tried.add(url)
        try:
            oa_resolver.download_pdf(url, pdf_file)
            return url
        except Exception as exc:
            logger.debug("Candidate PDF failed (%s): %s", url, exc)

    oa_res = oa_resolver.resolve(doi=doi_norm, url=article.url, oa_hint=article.oa)
    if oa_res.is_oa and oa_res.pdf_url and oa_res.pdf_url not in tried:
        tried.add(oa_res.pdf_url)
        try:
            oa_resolver.download_pdf(oa_res.pdf_url, pdf_file)
            return oa_res.pdf_url
        except Exception as exc:
            logger.debug("Resolved OA PDF failed (%s): %s", oa_res.pdf_url, exc)

    return None


def run_pipeline(
    *,
    out_dir: str | Path = "site/data",
    max_articles: int = 5,
    feed_limit: int = 300,
    period_days: int | None = 30,
    date_from: str | None = None,
    date_to: str | None = None,
    journals: Sequence[str] | None = None,
    use_llm_screening: bool = True,
    use_openalex: bool = True,
    progress_callback: Callable[[str], None] | None = None,
) -> list[CatalogEntry]:
    """Run one full ingestion + extraction + build cycle for the chosen date period."""
    out_path = Path(out_dir)
    problems_dir = out_path / "problems"
    problems_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = out_path / "catalog.json"

    start_date, end_date = resolve_date_window(
        period_days=period_days,
        date_from=date_from,
        date_to=date_to,
    )
    _emit(progress_callback, f"Scanning period: {start_date} .. {end_date} (max {max_articles})")

    existing_entries, known_dois = load_catalog(catalog_path)

    llm = MultiProviderLLM()
    has_text_llm = llm.groq.is_configured or llm.nvidia.is_configured or llm.gemini.is_configured
    if not has_text_llm:
        _emit(
            progress_callback,
            "No LLM API keys configured (GEMINI_API_KEY / GROQ_API_KEY / NVIDIA_API_KEY). Exiting cleanly.",
        )
        return []

    articles: list[RawArticle] = []
    seen_keys: set[str] = set()

    def _add_article(art: RawArticle) -> None:
        doi_k = normalize_doi(art.doi).lower()
        key = doi_k or art.title.strip().lower()
        if not key or key in seen_keys:
            return
        seen_keys.add(key)
        articles.append(art)

    if use_openalex:
        try:
            with OpenAlexClient() as oa_client:
                oa_articles = oa_client.search_total_synthesis(
                    date_from=start_date,
                    date_to=end_date,
                    limit=max(50, max_articles * 12),
                )
            _emit(progress_callback, f"OpenAlex returned {len(oa_articles)} OA total-synthesis candidates")
            for art in oa_articles:
                _add_article(art)
        except Exception as exc:
            _emit(progress_callback, f"OpenAlex search failed: {exc}")

    try:
        with ChemASAPClient() as chemasap:
            feed_articles: list[RawArticle] = chemasap.fetch_latest_articles(
                journals=journals,
                limit=feed_limit,
            )
        in_range = [a for a in feed_articles if _within_date_range(a.published_at, start_date, end_date)]
        _emit(progress_callback, f"ChemASAP returned {len(in_range)}/{len(feed_articles)} articles in date window")
        for art in in_range:
            _add_article(art)
    except Exception as exc:
        _emit(progress_callback, f"ChemASAP fetch failed: {exc}")

    _emit(progress_callback, f"Total deduplicated candidates to inspect: {len(articles)}")

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
                        _emit(progress_callback, f"LLM screening rejected: {article.title[:80]}")
                        continue
                except Exception as exc:
                    logger.warning("LLM screening failed for %s: %s", article.title, exc)

            if not llm.gemini.is_configured:
                _emit(progress_callback, "GEMINI_API_KEY is required for multimodal PDF extraction; stopping.")
                break

            pdf_file = tmp_path / f"article_{processed_count}.pdf"
            downloaded_pdf_url = _download_article_pdf(article, doi_norm, oa_resolver, pdf_file)
            if not downloaded_pdf_url:
                _emit(progress_callback, f"No downloadable OA PDF for: {article.title[:70]} ({doi_norm})")
                continue

            _emit(progress_callback, f"Extracting synthesis from PDF: {article.title[:75]}")
            try:
                extraction = extract_synthesis_from_pdf(
                    pdf_path=pdf_file,
                    title=article.title,
                    authors=_split_authors(article.authors),
                    journal=article.journal,
                    year=_parse_year(article.published_at),
                    doi=doi_norm,
                    pdf_url=downloaded_pdf_url,
                    source_url=article.url,
                    llm=llm,
                    render_svgs=True,
                )
            except Exception as exc:
                _emit(progress_callback, f"Extraction failed for {article.title[:60]}: {exc}")
                continue

            problem = extraction.problem
            if not problem.steps:
                _emit(progress_callback, f"No synthesis steps extracted for {article.title[:60]}; skipping")
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
            _emit(progress_callback, f"Added synthesis: {entry.target_molecule} ({entry.num_steps} steps)")

    run_meta = {
        "last_period": {"date_from": start_date, "date_to": end_date},
        "last_added": len(new_entries),
    }
    if new_entries:
        merged = [e.to_dict() for e in new_entries] + existing_entries
        save_catalog(catalog_path, merged, extra_meta=run_meta)
        _emit(progress_callback, f"Updated catalog with {len(new_entries)} new problem(s).")
    else:
        save_catalog(catalog_path, existing_entries, extra_meta=run_meta)
        _emit(progress_callback, "Scan finished: no new downloadable synthesis problems added.")

    return new_entries


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for synthesis-finder."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Fetch, extract, build, or delete total synthesis problems.")
    parser.add_argument("--max-articles", type=int, default=5, help="Max new problems to extract per run")
    parser.add_argument("--feed-limit", type=int, default=300, help="Number of recent ChemASAP articles to scan")
    parser.add_argument("--period-days", type=int, default=30, help="Lookback period in days when --date-from is omitted")
    parser.add_argument("--date-from", type=str, default=None, help="Start publication date (YYYY-MM-DD)")
    parser.add_argument("--date-to", type=str, default=None, help="End publication date (YYYY-MM-DD)")
    parser.add_argument("--out-dir", type=str, default="site/data", help="Output data directory")
    parser.add_argument("--no-llm-screen", action="store_true", help="Skip LLM screening step")
    parser.add_argument("--no-openalex", action="store_true", help="Disable OpenAlex search source")
    parser.add_argument("--delete-ids", type=str, default=None, help="Comma-separated problem IDs to delete")
    parser.add_argument("--delete-all", action="store_true", help="Delete all synthesis problems from catalog")
    args = parser.parse_args(argv)

    if args.delete_all or args.delete_ids:
        ids = [x.strip() for x in (args.delete_ids or "").split(",") if x.strip()]
        delete_problems(out_dir=args.out_dir, problem_ids=ids, delete_all=args.delete_all)
        return 0

    run_pipeline(
        out_dir=args.out_dir,
        max_articles=args.max_articles,
        feed_limit=args.feed_limit,
        period_days=args.period_days,
        date_from=args.date_from or None,
        date_to=args.date_to or None,
        use_llm_screening=not args.no_llm_screen,
        use_openalex=not args.no_openalex,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
