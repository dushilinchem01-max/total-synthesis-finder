"""Unit tests for ChemASAP client, OA PDF resolver, and article filter."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from synthesis_finder.article_filter import ArticleFilter, filter_articles, heuristic_filter
from synthesis_finder.chemasap_client import ChemASAPClient, ChemASAPError, RawArticle
from synthesis_finder.oa_resolver import OAResolver, normalize_doi


def _make_mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestChemASAPClient:
    def test_fetch_journals(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/journals"
            return httpx.Response(
                200,
                json=[{"id": "jacs", "code": "JACS", "name": "Journal of the American Chemical Society"}],
            )

        with ChemASAPClient(client=_make_mock_client(handler)) as client:
            journals = client.fetch_journals()

        assert len(journals) == 1
        assert journals[0]["id"] == "jacs"

    def test_fetch_latest_articles_parses_fields_and_params(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/feed"
            assert request.url.params["journals"] == "jacs,ol"
            assert request.url.params["limit"] == "10"
            assert request.url.params["offset"] == "5"
            return httpx.Response(
                200,
                json={
                    "updatedAt": "2026-11-26T08:35:44Z",
                    "total": 1,
                    "articles": [
                        {
                            "id": "abc123",
                            "title": "Total Synthesis of (&plusmn;)-Gnetin C",
                            "authors": "Jane Doe, John Smith",
                            "journalId": "ol",
                            "journalName": "Organic Letters",
                            "journalAbbr": "Org. Lett.",
                            "doi": "10.1021/acs.orglett.6c04969",
                            "abstract": "<p>A concise <b>total synthesis</b> is reported.</p>",
                            "link": "https://pubs.acs.org/doi/10.1021/acs.orglett.6c04969",
                            "imageUrl": "https://api.baranlab.org/api/img?url=toc.png",
                            "publishedAt": "2026-11-26T07:00:00Z",
                            "sourceType": "journal",
                            "oa": True,
                        }
                    ],
                },
            )

        with ChemASAPClient(client=_make_mock_client(handler)) as client:
            articles = client.fetch_latest_articles(journals=["jacs", "ol"], limit=10, offset=5)

        assert len(articles) == 1
        art = articles[0]
        assert art.id == "abc123"
        assert art.title == "Total Synthesis of (±)-Gnetin C"
        assert art.abstract == "A concise total synthesis is reported."
        assert art.journal == "Organic Letters"
        assert art.journal_abbr == "Org. Lett."
        assert art.doi == "10.1021/acs.orglett.6c04969"
        assert art.toc_image_url == "https://api.baranlab.org/api/img?url=toc.png"
        assert art.oa is True

    def test_fetch_latest_articles_falls_back_to_chemrxiv(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "api.baranlab.org" in str(request.url):
                return httpx.Response(503, text="Service Unavailable")
            return httpx.Response(
                200,
                json={
                    "itemHits": [
                        {
                            "item": {
                                "id": "cr-1",
                                "doi": "10.26434/chemrxiv.15012664/v1",
                                "title": "Solid-Phase Total Synthesis of Wewakazole B",
                                "abstract": "Total synthesis of cyclic peptide natural product.",
                                "authors": [{"firstName": "Alice", "lastName": "Chem"}],
                                "publishedDate": "2026-11-25T12:00:00Z",
                            }
                        }
                    ]
                },
            )

        with ChemASAPClient(client=_make_mock_client(handler)) as client:
            articles = client.fetch_latest_articles(limit=5)

        assert len(articles) == 1
        assert articles[0].journal_id == "chemrxiv"
        assert articles[0].authors == "Alice Chem"
        assert articles[0].oa is True

    def test_fetch_latest_articles_raises_when_fallback_disabled(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        with ChemASAPClient(client=_make_mock_client(handler)) as client:
            with pytest.raises(ChemASAPError):
                client.fetch_latest_articles(fallback_to_chemrxiv=False)


class TestOAResolver:
    def test_normalize_doi(self) -> None:
        assert normalize_doi("https://doi.org/10.1021/acs.orglett.6c04969") == "10.1021/acs.orglett.6c04969"
        assert normalize_doi("doi: 10.1002/anie.12345/") == "10.1002/anie.12345"

    def test_direct_pdf_url(self) -> None:
        resolver = OAResolver(client=_make_mock_client(lambda req: httpx.Response(404)))
        res = resolver.resolve(url="https://example.org/paper.pdf?download=1")
        assert res.is_oa is True
        assert res.source == "direct_pdf"
        assert res.pdf_url == "https://example.org/paper.pdf?download=1"

    def test_chemrxiv_resolution(self) -> None:
        resolver = OAResolver(client=_make_mock_client(lambda req: httpx.Response(404)))
        res = resolver.resolve(
            doi="10.26434/chemrxiv.15012664/v1",
            url="https://chemrxiv.org/doi/full/10.26434/chemrxiv.15012664/v1",
        )
        assert res.is_oa is True
        assert res.source == "chemrxiv"
        assert res.pdf_url == "https://chemrxiv.org/doi/pdf/10.26434/chemrxiv.15012664/v1"

    def test_unpaywall_resolution(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "api.unpaywall.org" in str(request.url)
            assert request.url.params["email"] == "test@lab.org"
            return httpx.Response(
                200,
                json={
                    "is_oa": True,
                    "best_oa_location": {
                        "url_for_pdf": "https://repo.example.org/oa.pdf",
                        "url_for_landing_page": "https://repo.example.org/oa",
                    },
                },
            )

        with OAResolver(unpaywall_email="test@lab.org", client=_make_mock_client(handler)) as resolver:
            res = resolver.resolve(doi="10.1002/anie.6282262")

        assert res.is_oa is True
        assert res.source == "unpaywall"
        assert res.pdf_url == "https://repo.example.org/oa.pdf"

    def test_europepmc_fallback_when_unpaywall_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "api.unpaywall.org" in str(request.url):
                return httpx.Response(200, json={"is_oa": False})
            return httpx.Response(
                200,
                json={
                    "resultList": {
                        "result": [
                            {
                                "pmcid": "PMC9999999",
                                "isOpenAccess": "Y",
                                "fullTextUrlList": {
                                    "fullTextUrl": [
                                        {
                                            "documentStyle": "pdf",
                                            "availabilityCode": "OA",
                                            "url": "https://europepmc.org/articles/PMC9999999?pdf=render",
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                },
            )

        with OAResolver(client=_make_mock_client(handler)) as resolver:
            res = resolver.resolve(doi="10.1021/jacs.12345")

        assert res.is_oa is True
        assert res.source == "europepmc"
        assert res.pdf_url == "https://europepmc.org/articles/PMC9999999?pdf=render"

    def test_publisher_oa_fallback_with_hint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        with OAResolver(client=_make_mock_client(handler)) as resolver:
            res = resolver.resolve(
                doi="10.1021/acs.orglett.6c04969",
                url="https://pubs.acs.org/doi/10.1021/acs.orglett.6c04969",
                oa_hint=True,
            )

        assert res.is_oa is True
        assert res.source == "publisher_oa"
        assert res.pdf_url == "https://pubs.acs.org/doi/pdf/10.1021/acs.orglett.6c04969"

    def test_verify_pdf_and_download(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(200, headers={"content-type": "application/pdf"})
            return httpx.Response(200, content=b"%PDF-1.7\n%mock")

        with OAResolver(client=_make_mock_client(handler), verify_pdf=True) as resolver:
            res = resolver.resolve(url="https://example.org/good.pdf")
            assert res.pdf_url == "https://example.org/good.pdf"
            out = resolver.download_pdf(res.pdf_url, tmp_path / "paper.pdf")
            assert out.read_bytes().startswith(b"%PDF")


class TestArticleFilter:
    def test_heuristic_accepts_total_synthesis(self) -> None:
        res = heuristic_filter(
            title="Total Synthesis of (±)-Gnetin C and Congeners",
            abstract="A biomimetic diastereoselective synthesis of the natural product is described.",
        )
        assert res.passed is True
        assert res.score >= 0.65
        assert "total synthesis" in res.matched_keywords

    def test_heuristic_rejects_review_and_dft(self) -> None:
        review_res = heuristic_filter(
            title="Recent Advances in Total Synthesis: A Review",
            abstract="This review summarizes recent total synthesis efforts.",
        )
        assert review_res.passed is False

        dft_res = heuristic_filter(
            title="DFT Study of Palladium-Catalyzed Coupling",
            abstract="A computational study using molecular dynamics and DFT.",
        )
        assert dft_res.passed is False

    def test_llm_hook_filters_candidates(self) -> None:
        articles = [
            RawArticle(
                id="1",
                title="Total Synthesis of Diplodiatoxin",
                authors="A. Author",
                journal="Angew. Chem.",
                journal_id="anie",
                journal_abbr="Angew. Chem.",
                doi="10.1002/anie.1",
                abstract="A modular Diels-Alder total synthesis.",
                url="https://example.org/1",
                toc_image_url=None,
                published_at="2026-11-26",
            ),
            RawArticle(
                id="2",
                title="Total Synthesis of Polymeric MOFs",
                authors="B. Author",
                journal="JACS",
                journal_id="jacs",
                journal_abbr="JACS",
                doi="10.1021/jacs.2",
                abstract="Total synthesis of metal-organic framework materials.",
                url="https://example.org/2",
                toc_image_url=None,
                published_at="2026-11-26",
            ),
        ]

        def fake_llm(title: str, abstract: str) -> tuple[bool, str]:
            if "Diplodiatoxin" in title:
                return True, "natural product total synthesis"
            return False, "materials synthesis, not organic natural product"

        kept = filter_articles(articles, llm_classifier=fake_llm)
        assert len(kept) == 1
        assert kept[0][0].id == "1"
        assert kept[0][1].llm_verified is True

        # Also test ArticleFilter directly with bool-returning hook
        af = ArticleFilter(llm_classifier=lambda t, a: "Diplodiatoxin" in t)
        assert len(af.filter_articles(articles)) == 1


@pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="Set RUN_LIVE_TESTS=1 for live smoke test")
def test_live_chemasap_smoke() -> None:
    with ChemASAPClient() as client:
        articles = client.fetch_latest_articles(journals=["jacs", "ol", "chemrxiv"], limit=10)
    assert len(articles) > 0
    assert all(a.title for a in articles)
