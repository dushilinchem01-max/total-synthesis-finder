"""Open-Access PDF resolution from DOI or article URL."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
from urllib.parse import quote, urlparse

import httpx

logger = logging.getLogger(__name__)

_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


@dataclass(slots=True)
class OAResolution:
    """Result of resolving an article DOI/URL to an Open-Access PDF."""

    doi: str
    pdf_url: str | None
    source: str
    is_oa: bool
    landing_url: str | None = None
    error: str | None = None


def normalize_doi(doi: str | None) -> str:
    """Strip common URL/prefix wrappers from a DOI string."""
    if not doi:
        return ""
    cleaned = _DOI_PREFIX_RE.sub("", doi.strip())
    return cleaned.strip("/")


def _looks_like_pdf_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


class OAResolver:
    """Resolve Open-Access PDF URLs via ChemRxiv, Unpaywall, EuropePMC, and direct links."""

    UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
    EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(
        self,
        unpaywall_email: str | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
        verify_pdf: bool = False,
    ) -> None:
        self.unpaywall_email = (
            unpaywall_email
            or os.environ.get("UNPAYWALL_EMAIL")
            or "synthesis-finder@users.noreply.github.com"
        )
        self.verify_pdf = verify_pdf
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "synthesis-finder/0.1 (OA resolver)"},
        )

    def __enter__(self) -> OAResolver:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client:
            self._client.close()

    def resolve(
        self,
        doi: str | None = None,
        url: str | None = None,
        oa_hint: bool | None = None,
    ) -> OAResolution:
        """Resolve an open-access PDF URL for the given DOI and/or article URL."""
        norm_doi = normalize_doi(doi)
        clean_url = (url or "").strip() or None

        # 1. Direct PDF URL
        if clean_url and _looks_like_pdf_url(clean_url):
            if self._accept_pdf_url(clean_url):
                return OAResolution(
                    doi=norm_doi,
                    pdf_url=clean_url,
                    source="direct_pdf",
                    is_oa=True,
                    landing_url=clean_url,
                )

        # 2. ChemRxiv direct PDF resolution
        chemrxiv_pdf = self._resolve_chemrxiv(norm_doi, clean_url)
        if chemrxiv_pdf and self._accept_pdf_url(chemrxiv_pdf):
            return OAResolution(
                doi=norm_doi,
                pdf_url=chemrxiv_pdf,
                source="chemrxiv",
                is_oa=True,
                landing_url=clean_url or f"https://chemrxiv.org/doi/full/{norm_doi}",
            )

        # 3. Unpaywall API
        if norm_doi:
            unpaywall_res = self._resolve_unpaywall(norm_doi)
            if unpaywall_res and unpaywall_res.pdf_url and self._accept_pdf_url(unpaywall_res.pdf_url):
                return unpaywall_res

            # 4. EuropePMC API
            epmc_res = self._resolve_europepmc(norm_doi)
            if epmc_res and epmc_res.pdf_url and self._accept_pdf_url(epmc_res.pdf_url):
                return epmc_res

        # 5. Publisher OA heuristic when ChemASAP already marked article as OA
        if oa_hint and clean_url:
            heuristic_pdf = self._publisher_oa_pdf(clean_url, norm_doi)
            if heuristic_pdf and self._accept_pdf_url(heuristic_pdf):
                return OAResolution(
                    doi=norm_doi,
                    pdf_url=heuristic_pdf,
                    source="publisher_oa",
                    is_oa=True,
                    landing_url=clean_url,
                )

        return OAResolution(
            doi=norm_doi,
            pdf_url=None,
            source="none",
            is_oa=bool(oa_hint),
            landing_url=clean_url,
        )

    def _resolve_chemrxiv(self, doi: str, url: str | None) -> str | None:
        if doi.lower().startswith("10.26434/chemrxiv"):
            return f"https://chemrxiv.org/doi/pdf/{doi}"
        if url and "chemrxiv.org" in url.lower():
            if "/doi/full/" in url:
                return url.replace("/doi/full/", "/doi/pdf/", 1)
            if "/doi/abs/" in url:
                return url.replace("/doi/abs/", "/doi/pdf/", 1)
        return None

    def _resolve_unpaywall(self, doi: str) -> OAResolution | None:
        endpoint = f"{self.UNPAYWALL_BASE}/{quote(doi, safe='')}"
        try:
            resp = self._client.get(endpoint, params={"email": self.unpaywall_email})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("Unpaywall lookup failed for %s: %s", doi, exc)
            return None

        if not isinstance(data, dict) or not data.get("is_oa"):
            return None

        best = data.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf") if isinstance(best, dict) else None
        landing = best.get("url_for_landing_page") if isinstance(best, dict) else None

        if not pdf_url:
            for loc in data.get("oa_locations") or []:
                if isinstance(loc, dict) and loc.get("url_for_pdf"):
                    pdf_url = loc["url_for_pdf"]
                    landing = landing or loc.get("url_for_landing_page")
                    break

        if not pdf_url:
            return None

        return OAResolution(
            doi=doi,
            pdf_url=pdf_url,
            source="unpaywall",
            is_oa=True,
            landing_url=landing,
        )

    def _resolve_europepmc(self, doi: str) -> OAResolution | None:
        try:
            resp = self._client.get(
                self.EUROPEPMC_SEARCH,
                params={
                    "query": f'DOI:"{doi}"',
                    "format": "json",
                    "resultType": "core",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("EuropePMC lookup failed for %s: %s", doi, exc)
            return None

        results = (data.get("resultList") or {}).get("result") or []
        for item in results:
            if not isinstance(item, dict):
                continue
            ft_urls = ((item.get("fullTextUrlList") or {}).get("fullTextUrl")) or []
            for entry in ft_urls:
                if (
                    isinstance(entry, dict)
                    and str(entry.get("documentStyle", "")).lower() == "pdf"
                    and str(entry.get("availabilityCode", "")).upper() in {"OA", "F"}
                    and entry.get("url")
                ):
                    return OAResolution(
                        doi=doi,
                        pdf_url=str(entry["url"]),
                        source="europepmc",
                        is_oa=True,
                        landing_url=None,
                    )
            pmcid = item.get("pmcid")
            if pmcid and str(item.get("isOpenAccess", "")).upper() == "Y":
                return OAResolution(
                    doi=doi,
                    pdf_url=f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf",
                    source="europepmc",
                    is_oa=True,
                    landing_url=f"https://europepmc.org/article/PMC/{pmcid}",
                )
        return None

    def _publisher_oa_pdf(self, url: str, doi: str) -> str | None:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "pubs.acs.org" in host and doi:
            return f"https://pubs.acs.org/doi/pdf/{doi}"
        if "onlinelibrary.wiley.com" in host and doi:
            return f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"
        return None

    def _accept_pdf_url(self, pdf_url: str) -> bool:
        if not self.verify_pdf:
            return True
        try:
            resp = self._client.head(pdf_url)
            if resp.status_code == 405:
                resp = self._client.get(pdf_url, headers={"Range": "bytes=0-1023"})
            if resp.status_code >= 400:
                return False
            ctype = resp.headers.get("content-type", "").lower()
            return "pdf" in ctype or resp.content.startswith(b"%PDF")
        except httpx.HTTPError:
            return False

    def download_pdf(self, pdf_url: str, dest_path: str | Path) -> Path:
        """Download a PDF to ``dest_path`` and verify it starts with ``%PDF``."""
        target = Path(dest_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        resp = self._client.get(pdf_url)
        resp.raise_for_status()
        content = resp.content
        if not content.startswith(b"%PDF"):
            raise ValueError(f"URL did not return a valid PDF payload: {pdf_url}")
        target.write_bytes(content)
        return target
