"""Tests for OpenAlex client, period filtering, problem deletion, and Auth/Admin server."""

from __future__ import annotations

from datetime import date
import io
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from synthesis_finder.models import CatalogEntry, SynthesisProblem, SynthesisStep
from synthesis_finder.openalex_client import OpenAlexClient, reconstruct_abstract, resolve_date_window
from synthesis_finder.pipeline import delete_problems, save_catalog
from synthesis_finder.server import create_server


def test_reconstruct_abstract_and_date_window() -> None:
    text = reconstruct_abstract({"Total": [0], "synthesis": [1], "of": [2], "taxol": [3]})
    assert text == "Total synthesis of taxol"
    assert reconstruct_abstract(None) == ""

    d_from, d_to = resolve_date_window(period_days=30, today=date(2026, 11, 26))
    assert d_from == "2026-10-27"
    assert d_to == "2026-11-26"

    c_from, c_to = resolve_date_window(date_from="2026-01-01", date_to="2026-03-01")
    assert (c_from, c_to) == ("2026-01-01", "2026-03-01")


def test_openalex_client_parses_and_prioritizes_pdfs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.3762/bjoc.22.138",
                        "title": "Total synthesis of aspergilal",
                        "publication_date": "2026-11-10",
                        "abstract_inverted_index": {"Concise": [0], "synthesis.": [1]},
                        "open_access": {"is_oa": True},
                        "best_oa_location": {
                            "pdf_url": "https://www.beilstein-journals.org/bjoc/content/pdf/1860-5397-22-138.pdf"
                        },
                        "locations": [
                            {"pdf_url": "https://www.beilstein-journals.org/bjoc/content/pdf/1860-5397-22-138.pdf"}
                        ],
                        "primary_location": {
                            "landing_page_url": "https://www.beilstein-journals.org/bjoc/articles/22/138",
                            "source": {"id": "S1", "display_name": "Beilstein J. Org. Chem."},
                        },
                        "authorships": [{"author": {"display_name": "A. Chemist"}}],
                    }
                ]
            },
        )

    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    with OpenAlexClient(client=mock_http) as client:
        articles = client.search_total_synthesis(date_from="2026-10-01", date_to="2026-11-26", limit=10)

    assert len(articles) == 1
    assert articles[0].doi == "10.3762/bjoc.22.138"
    assert articles[0].abstract == "Concise synthesis."
    assert articles[0].candidate_pdf_urls == [
        "https://www.beilstein-journals.org/bjoc/content/pdf/1860-5397-22-138.pdf"
    ]


def test_delete_problems_single_and_all(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    probs_dir = data_dir / "problems"
    probs_dir.mkdir(parents=True)

    p1 = SynthesisProblem(id="p1", title="P1", target_molecule="Mol1", steps=[SynthesisStep(step_index=1)])
    p2 = SynthesisProblem(id="p2", title="P2", target_molecule="Mol2", steps=[SynthesisStep(step_index=1)])
    for p in (p1, p2):
        (probs_dir / f"{p.id}.json").write_text(p.to_json(), encoding="utf-8")
        (probs_dir / f"{p.id}.html").write_text("<html></html>", encoding="utf-8")

    entries = [CatalogEntry.from_problem(p1).to_dict(), CatalogEntry.from_problem(p2).to_dict()]
    save_catalog(data_dir / "catalog.json", entries)

    removed = delete_problems(data_dir, ["p1"])
    assert removed == ["p1"]
    assert not (probs_dir / "p1.json").exists()
    assert not (probs_dir / "p1.html").exists()
    assert (probs_dir / "p2.json").exists()

    removed_all = delete_problems(data_dir, delete_all=True)
    assert removed_all == ["p2"]
    assert not (probs_dir / "p2.json").exists()
    cat = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    assert cat["problems"] == []


def _dispatch_handler(server, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    """Invoke RequestHandlerClass in-memory without opening an outbound TCP socket."""
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = [f"{method} {path} HTTP/1.1", "Host: localhost"]
    if body is not None:
        headers.append("Content-Type: application/json")
        headers.append(f"Content-Length: {len(raw_body)}")
    if token:
        headers.append(f"Authorization: Bearer {token}")
    request_bytes = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + raw_body

    class _FakeSocket:
        def __init__(self, data: bytes) -> None:
            self._rfile = io.BytesIO(data)
            self.wfile = io.BytesIO()

        def makefile(self, mode: str, *args, **kwargs):
            return self._rfile if "r" in mode else self.wfile

        def sendall(self, data: bytes) -> None:
            self.wfile.write(data)

        def close(self) -> None:
            pass

    sock = _FakeSocket(request_bytes)
    server.RequestHandlerClass(sock, ("127.0.0.1", 0), server)
    raw_resp = sock.wfile.getvalue().decode("utf-8", errors="replace")
    head, _, resp_body = raw_resp.partition("\r\n\r\n")
    status_code = int(head.splitlines()[0].split()[1])
    return status_code, json.loads(resp_body) if resp_body.strip() else {}


def test_server_auth_and_admin_endpoints(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    data_dir = site_dir / "data"
    probs_dir = data_dir / "problems"
    probs_dir.mkdir(parents=True)
    (site_dir / "index.html").write_text("<h1>SynthesisFinder</h1>", encoding="utf-8")

    p1 = SynthesisProblem(id="demo-1", title="Demo 1", target_molecule="Target 1")
    (probs_dir / "demo-1.json").write_text(p1.to_json(), encoding="utf-8")
    (probs_dir / "demo-1.html").write_text("<html></html>", encoding="utf-8")
    save_catalog(data_dir / "catalog.json", [CatalogEntry.from_problem(p1).to_dict()])

    users_file = tmp_path / "users.json"
    server = create_server(host="127.0.0.1", port=0, site_dir=site_dir, users_file=users_file)

    try:
        st, health = _dispatch_handler(server, "GET", "/api/health")
        assert st == 200 and health["ok"] is True

        # Unauthenticated admin request -> 401
        st, _ = _dispatch_handler(server, "POST", "/api/admin/update", {"period_days": 7})
        assert st == 401

        # Register regular user -> cannot access admin endpoints (403)
        st, reg = _dispatch_handler(server, "POST", "/api/auth/register", {"username": "chemist1", "password": "secret"})
        assert st == 201
        user_token = reg["token"]
        assert reg["user"]["role"] == "user"

        st, _ = _dispatch_handler(server, "DELETE", "/api/admin/problems/demo-1", token=user_token)
        assert st == 403

        # Login as seeded admin/admin -> full access
        st, login = _dispatch_handler(server, "POST", "/api/auth/login", {"username": "admin", "password": "admin"})
        assert st == 200
        admin_token = login["token"]
        assert login["user"]["role"] == "admin"

        # Delete problem as admin
        st, del_resp = _dispatch_handler(server, "DELETE", "/api/admin/problems/demo-1", token=admin_token)
        assert st == 200 and del_resp["deleted"] is True
        assert not (probs_dir / "demo-1.json").exists()

        # Trigger update as admin (mocking run_pipeline)
        with patch("synthesis_finder.server.run_pipeline", return_value=[]) as mock_run:
            st, upd = _dispatch_handler(
                server,
                "POST",
                "/api/admin/update",
                {"date_from": "2026-10-01", "date_to": "2026-11-26", "max_articles": 3},
                token=admin_token,
            )
            assert st == 202
            assert upd["period"]["date_from"] == "2026-10-01"
            assert upd["period"]["date_to"] == "2026-11-26"
            mock_run.assert_called()
    finally:
        server.server_close()
