"""Client for fetching latest chemistry articles from ChemASAP (api.baranlab.org)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from html import unescape
import logging
import re
from typing import Any, Sequence

import httpx

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


class ChemASAPError(RuntimeError):
    """Raised when fetching articles from ChemASAP and its fallbacks fails."""


@dataclass(slots=True)
class RawArticle:
    """Normalized article record returned by ChemASAP or fallback feeds."""

    id: str
    title: str
    authors: str
    journal: str
    journal_id: str
    journal_abbr: str
    doi: str
    abstract: str
    url: str
    toc_image_url: str | None
    published_at: str
    source_type: str = "journal"
    oa: bool | None = None
    candidate_pdf_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize article to a plain dictionary."""
        return asdict(self)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = _TAG_RE.sub("", unescape(value))
    return " ".join(text.split())


def _parse_chemasap_article(item: dict[str, Any]) -> RawArticle:
    title = _clean_text(item.get("title") or item.get("titleHtml"))
    abstract = _clean_text(item.get("abstract") or item.get("abstractHtml"))
    journal = (
        item.get("journalName")
        or item.get("journalAbbr")
        or item.get("journalId")
        or ""
    )
    oa_raw = item.get("oa")
    oa: bool | None = oa_raw if isinstance(oa_raw, bool) else None

    return RawArticle(
        id=str(item.get("id") or ""),
        title=title,
        authors=_clean_text(item.get("authors")),
        journal=journal,
        journal_id=str(item.get("journalId") or ""),
        journal_abbr=str(item.get("journalAbbr") or journal),
        doi=str(item.get("doi") or "").strip(),
        abstract=abstract,
        url=str(item.get("link") or "").strip(),
        toc_image_url=item.get("imageUrl") or None,
        published_at=str(item.get("publishedAt") or ""),
        source_type=str(item.get("sourceType") or "journal"),
        oa=oa,
    )


def _parse_chemrxiv_item(item: dict[str, Any]) -> RawArticle:
    doi = str(item.get("doi") or "").strip()
    authors_list = item.get("authors") or []
    author_names = [
        f"{a.get('firstName', '')} {a.get('lastName', '')}".strip()
        for a in authors_list
        if isinstance(a, dict)
    ]
    authors = ", ".join(name for name in author_names if name)
    item_id = str(item.get("id") or doi)
    url = f"https://chemrxiv.org/doi/full/{doi}" if doi else ""
    asset = item.get("asset") or {}
    thumb_url = None
    if isinstance(asset, dict):
        original = asset.get("original") or {}
        if isinstance(original, dict):
            thumb_url = original.get("url")

    return RawArticle(
        id=item_id,
        title=_clean_text(item.get("title")),
        authors=authors,
        journal="ChemRxiv",
        journal_id="chemrxiv",
        journal_abbr="ChemRxiv",
        doi=doi,
        abstract=_clean_text(item.get("abstract")),
        url=url,
        toc_image_url=thumb_url,
        published_at=str(item.get("publishedDate") or item.get("statusDate") or ""),
        source_type="preprint",
        oa=True,
    )


class ChemASAPClient:
    """HTTP client for the ChemASAP API at https://api.baranlab.org."""

    BASE_URL = "https://api.baranlab.org"
    CHEMRXIV_API_URL = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "synthesis-finder/0.1 (ChemASAP client)"},
        )

    def __enter__(self) -> ChemASAPClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client:
            self._client.close()

    def fetch_journals(self) -> list[dict[str, Any]]:
        """Fetch the list of supported journals from ``/api/journals``."""
        try:
            resp = self._client.get(f"{self.base_url}/api/journals")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ChemASAPError(f"Failed to fetch ChemASAP journals: {exc}") from exc

        if not isinstance(data, list):
            raise ChemASAPError("Unexpected /api/journals response format: expected list")
        return data

    def fetch_latest_articles(
        self,
        journals: Sequence[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        fallback_to_chemrxiv: bool = True,
    ) -> list[RawArticle]:
        """Fetch latest articles from ``/api/feed`` with optional ChemRxiv fallback.

        Args:
            journals: Optional list of ChemASAP journal IDs (e.g. ``["jacs", "ol", "chemrxiv"]``).
            limit: Maximum number of articles to return (0 means all in ChemASAP API).
            offset: Pagination offset.
            fallback_to_chemrxiv: If True, fall back to ChemRxiv public API when ChemASAP fails.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if journals:
            params["journals"] = ",".join(j.strip() for j in journals if j.strip())

        try:
            resp = self._client.get(f"{self.base_url}/api/feed", params=params)
            resp.raise_for_status()
            payload = resp.json()
            raw_articles = payload.get("articles") if isinstance(payload, dict) else None
            if not isinstance(raw_articles, list):
                raise ChemASAPError("Unexpected /api/feed response: missing 'articles' list")
            return [_parse_chemasap_article(item) for item in raw_articles if isinstance(item, dict)]
        except (httpx.HTTPError, ValueError, ChemASAPError) as exc:
            if not fallback_to_chemrxiv:
                raise ChemASAPError(f"Failed to fetch ChemASAP feed: {exc}") from exc
            logger.warning("ChemASAP feed failed (%s); falling back to ChemRxiv public API", exc)
            return self.fetch_chemrxiv_fallback(limit=limit or 50, offset=offset)

    def fetch_chemrxiv_fallback(self, limit: int = 50, offset: int = 0) -> list[RawArticle]:
        """Fetch recent preprints directly from the ChemRxiv public API."""
        try:
            resp = self._client.get(
                self.CHEMRXIV_API_URL,
                params={"limit": min(max(limit, 1), 50), "skip": offset},
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ChemASAPError(f"ChemRxiv fallback failed: {exc}") from exc

        items = payload.get("itemHits") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ChemASAPError("Unexpected ChemRxiv API response: missing 'itemHits'")

        articles: list[RawArticle] = []
        for hit in items:
            item = hit.get("item") if isinstance(hit, dict) and "item" in hit else hit
            if isinstance(item, dict):
                articles.append(_parse_chemrxiv_item(item))
        return articles
