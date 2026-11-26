"""Client for searching Open-Access total synthesis papers via OpenAlex & EuropePMC."""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any

import httpx

from synthesis_finder.chemasap_client import RawArticle
from synthesis_finder.oa_resolver import normalize_doi

logger = logging.getLogger(__name__)

# Hosts known to serve direct PDFs without bot challenges are prioritized first.
_PREFERRED_PDF_HOSTS = (
    "beilstein-journals.org",
    "nature.com",
    "mdpi.com",
    "arxiv.org",
    "zenodo.org",
    "hal.science",
    "ora.ox.ac.uk",
    "edoc.",
    "repository.",
    "repo.",
    "escholarship.org",
    "dspace.",
    "pure.",
    "frontiersin.org",
    "springer.com",
    "plos.org",
)


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Reconstruct plain-text abstract from an OpenAlex inverted index."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int):
                pairs.append((pos, str(word)))
    pairs.sort(key=lambda item: item[0])
    return " ".join(word for _, word in pairs)


def _pdf_url_priority(url: str) -> int:
    lower = url.lower()
    for idx, host in enumerate(_PREFERRED_PDF_HOSTS):
        if host in lower:
            return idx
    if "pmc.ncbi.nlm.nih.gov" in lower or "europepmc.org" in lower:
        return len(_PREFERRED_PDF_HOSTS) + 1
    return len(_PREFERRED_PDF_HOSTS) + 10


def _collect_openalex_pdf_urls(work: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    best = work.get("best_oa_location") or {}
    if isinstance(best, dict) and best.get("pdf_url"):
        urls.append(str(best["pdf_url"]).strip())

    for loc in work.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        pdf_url = str(loc.get("pdf_url") or "").strip()
        if pdf_url and pdf_url not in urls:
            urls.append(pdf_url)

    urls.sort(key=_pdf_url_priority)
    return urls


def _parse_openalex_work(work: dict[str, Any]) -> RawArticle:
    doi = normalize_doi(work.get("doi"))
    title = str(work.get("title") or work.get("display_name") or "").strip()
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))

    authors_list: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        name = str(author.get("display_name") or "").strip()
        if name:
            authors_list.append(name)

    primary_loc = work.get("primary_location") or {}
    source = (primary_loc.get("source") or {}) if isinstance(primary_loc, dict) else {}
    journal = str(source.get("display_name") or "Open Access").strip()

    landing_url = ""
    if isinstance(primary_loc, dict):
        landing_url = str(primary_loc.get("landing_page_url") or "").strip()
    if not landing_url and doi:
        landing_url = f"https://doi.org/{doi}"

    pdf_urls = _collect_openalex_pdf_urls(work)
    published_at = str(work.get("publication_date") or work.get("publication_year") or "").strip()
    work_id = str(work.get("id") or doi or title)

    return RawArticle(
        id=work_id,
        title=title,
        authors=", ".join(authors_list),
        journal=journal,
        journal_id=str(source.get("id") or "openalex"),
        journal_abbr=journal,
        doi=doi,
        abstract=abstract,
        url=landing_url,
        toc_image_url=None,
        published_at=published_at,
        source_type="openalex",
        oa=bool((work.get("open_access") or {}).get("is_oa", True)),
        candidate_pdf_urls=pdf_urls,
    )


def resolve_date_window(
    *,
    period_days: int | None = 30,
    date_from: str | None = None,
    date_to: str | None = None,
    today: date | None = None,
) -> tuple[str, str]:
    """Resolve (date_from, date_to) as YYYY-MM-DD strings."""
    ref_today = today or date.today()
    end_str = (date_to or "").strip() or ref_today.isoformat()
    start_str = (date_from or "").strip()
    if not start_str:
        days = max(1, int(period_days if period_days is not None else 30))
        try:
            end_dt = date.fromisoformat(end_str)
        except ValueError:
            end_dt = ref_today
            end_str = end_dt.isoformat()
        start_str = (end_dt - timedelta(days=days)).isoformat()
    return start_str, end_str


class OpenAlexClient:
    """Client for querying OpenAlex for Open-Access total synthesis publications."""

    BASE_URL = "https://api.openalex.org/works"

    def __init__(
        self,
        *,
        mailto: str = "synthesis-finder@users.noreply.github.com",
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.mailto = mailto
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": f"synthesis-finder/0.2 (mailto:{mailto})"},
        )

    def __enter__(self) -> OpenAlexClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search_total_synthesis(
        self,
        *,
        date_from: str,
        date_to: str,
        limit: int = 50,
    ) -> list[RawArticle]:
        """Fetch Open-Access total synthesis papers published within [date_from, date_to]."""
        per_page = min(max(limit, 1), 100)
        queries = (
            "total synthesis",
            "formal synthesis",
        )
        results: list[RawArticle] = []
        seen_keys: set[str] = set()

        for query in queries:
            if len(results) >= limit:
                break
            filter_expr = (
                f"title.search:{query},is_oa:true,"
                f"from_publication_date:{date_from},to_publication_date:{date_to}"
            )
            try:
                resp = self._client.get(
                    self.BASE_URL,
                    params={
                        "filter": filter_expr,
                        "sort": "publication_date:desc",
                        "per-page": per_page,
                        "mailto": self.mailto,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("OpenAlex query '%s' failed: %s", query, exc)
                continue

            works = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(works, list):
                continue

            for work in works:
                if not isinstance(work, dict):
                    continue
                art = _parse_openalex_work(work)
                if not art.title:
                    continue
                dedup_key = art.doi.lower() if art.doi else art.title.lower()
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                results.append(art)
                if len(results) >= limit:
                    break

        # Prioritize works that already expose preferred open-access repository/journal PDFs
        results.sort(
            key=lambda a: (
                0 if a.candidate_pdf_urls else 1,
                _pdf_url_priority(a.candidate_pdf_urls[0]) if a.candidate_pdf_urls else 999,
            )
        )
        return results
