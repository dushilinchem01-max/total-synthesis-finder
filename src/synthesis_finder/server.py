"""Lightweight stdlib HTTP server serving site/ plus auth & admin APIs."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from synthesis_finder.models import now_iso
from synthesis_finder.pipeline import delete_problems, run_pipeline

logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_PBKDF2_ITERS = 120_000


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return salt.hex(), dk.hex()


def _verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    _, candidate = _hash_password(password, salt_hex=salt_hex)
    return hmac.compare_digest(candidate, digest_hex)


class UserStore:
    """Simple JSON-backed user store with seeded default admin/admin account."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._users: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, str] = {}
        self._load_or_init()

    def _load_or_init(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._users = raw
                except Exception as exc:
                    logger.warning("Failed to read users file %s: %s", self.path, exc)
                    self._users = {}

            if "admin" not in self._users:
                salt, digest = _hash_password("admin")
                self._users["admin"] = {
                    "username": "admin",
                    "role": "admin",
                    "salt": salt,
                    "password_hash": digest,
                    "created_at": now_iso(),
                }
                self._save_unlocked()

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._users, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def authenticate(self, username: str, password: str) -> tuple[str, dict[str, str]] | None:
        uname = (username or "").strip().lower()
        with self._lock:
            rec = self._users.get(uname)
            if not rec:
                return None
            if not _verify_password(password or "", rec["salt"], rec["password_hash"]):
                return None
            token = secrets.token_urlsafe(32)
            self._sessions[token] = uname
            return token, {"username": rec["username"], "role": rec["role"]}

    def register(self, username: str, password: str) -> tuple[str, dict[str, str]]:
        uname_clean = (username or "").strip()
        uname_key = uname_clean.lower()
        if not _USERNAME_RE.match(uname_clean):
            raise ValueError("Логин должен содержать 3–32 символа (латиница, цифры, _, -, .).")
        if len(password or "") < 4:
            raise ValueError("Пароль должен быть не короче 4 символов.")

        with self._lock:
            if uname_key in self._users:
                raise ValueError("Пользователь с таким логином уже существует.")
            salt, digest = _hash_password(password)
            self._users[uname_key] = {
                "username": uname_clean,
                "role": "user",
                "salt": salt,
                "password_hash": digest,
                "created_at": now_iso(),
            }
            self._save_unlocked()
            token = secrets.token_urlsafe(32)
            self._sessions[token] = uname_key
            return token, {"username": uname_clean, "role": "user"}

    def get_user_by_token(self, token: str | None) -> dict[str, str] | None:
        if not token:
            return None
        with self._lock:
            uname = self._sessions.get(token)
            if not uname:
                return None
            rec = self._users.get(uname)
            if not rec:
                return None
            return {"username": rec["username"], "role": rec["role"]}

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)


class UpdateJobManager:
    """Manages background synthesis update runs and live status logs."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "period": None,
            "added_count": 0,
            "error": None,
            "logs": [],
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, "logs": list(self._state["logs"])}

    def _append_log(self, msg: str) -> None:
        with self._lock:
            self._state["logs"].append(f"[{now_iso()[11:19]}] {msg}")
            if len(self._state["logs"]) > 200:
                self._state["logs"] = self._state["logs"][-200:]

    def start_update(
        self,
        *,
        period_days: int | None = 30,
        date_from: str | None = None,
        date_to: str | None = None,
        max_articles: int = 5,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("Обновление синтезов уже выполняется.")
            self._state = {
                "running": True,
                "started_at": now_iso(),
                "finished_at": None,
                "period": {
                    "period_days": period_days,
                    "date_from": date_from,
                    "date_to": date_to,
                },
                "added_count": 0,
                "error": None,
                "logs": [f"[{now_iso()[11:19]}] Запуск обновления синтезов..."],
            }

        def _worker() -> None:
            saved_env: dict[str, str | None] = {}
            overrides = {k: v for k, v in (env_overrides or {}).items() if v}
            try:
                for k, v in overrides.items():
                    saved_env[k] = os.environ.get(k)
                    os.environ[k] = v

                added = run_pipeline(
                    out_dir=self.data_dir,
                    max_articles=max(1, min(int(max_articles), 30)),
                    period_days=period_days,
                    date_from=date_from or None,
                    date_to=date_to or None,
                    progress_callback=self._append_log,
                )
                with self._lock:
                    self._state["added_count"] = len(added)
                    self._state["finished_at"] = now_iso()
                    self._state["running"] = False
            except Exception as exc:
                logger.exception("Background pipeline update failed")
                self._append_log(f"Ошибка: {exc}")
                with self._lock:
                    self._state["error"] = str(exc)
                    self._state["finished_at"] = now_iso()
                    self._state["running"] = False
            finally:
                for k, old_val in saved_env.items():
                    if old_val is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = old_val

        thread = threading.Thread(target=_worker, name="synthesis-update", daemon=True)
        thread.start()
        return self.snapshot()


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    site_dir: str | Path = "site",
    users_file: str | Path = ".synthesis_finder_users.json",
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer serving site/ and /api/* routes."""
    site_path = Path(site_dir).resolve()
    data_path = site_path / "data"
    user_store = UserStore(Path(users_file).resolve())
    job_manager = UpdateJobManager(data_path)

    class SynthesisRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site_path), **kwargs)

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

        def end_headers(self) -> None:
            parsed_path = urlparse(self.path).path
            if parsed_path.startswith("/api/") or parsed_path.startswith("/data/"):
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _extract_token(self) -> str | None:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            return None

        def _current_user(self) -> dict[str, str] | None:
            return user_store.get_user_by_token(self._extract_token())

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            if length > 1_000_000:
                raise ValueError("Request body too large")
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _require_admin(self) -> dict[str, str] | None:
            user = self._current_user()
            if not user:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Требуется авторизация."})
                return None
            if user.get("role") != "admin":
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "Доступ только для администратора."})
                return None
            return user

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "mode": "server",
                        "has_gemini_key": bool(os.getenv("GEMINI_API_KEY")),
                        "has_text_llm": bool(
                            os.getenv("GROQ_API_KEY")
                            or os.getenv("NVIDIA_API_KEY")
                            or os.getenv("GEMINI_API_KEY")
                        ),
                    },
                )
                return

            if path == "/api/auth/me":
                self._send_json(HTTPStatus.OK, {"user": self._current_user()})
                return

            if path == "/api/admin/status":
                if not self._require_admin():
                    return
                self._send_json(HTTPStatus.OK, job_manager.snapshot())
                return

            super().do_GET()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                body = self._read_json_body()
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Некорректный JSON: {exc}"})
                return

            if path == "/api/auth/login":
                res = user_store.authenticate(
                    str(body.get("username") or ""),
                    str(body.get("password") or ""),
                )
                if not res:
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Неверный логин или пароль."})
                    return
                token, user = res
                self._send_json(HTTPStatus.OK, {"token": token, "user": user})
                return

            if path == "/api/auth/register":
                try:
                    token, user = user_store.register(
                        str(body.get("username") or ""),
                        str(body.get("password") or ""),
                    )
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(HTTPStatus.CREATED, {"token": token, "user": user})
                return

            if path == "/api/auth/logout":
                user_store.logout(self._extract_token())
                self._send_json(HTTPStatus.OK, {"ok": True})
                return

            if path == "/api/admin/update":
                if not self._require_admin():
                    return
                period_days_raw = body.get("period_days")
                period_days = int(period_days_raw) if period_days_raw not in (None, "") else 30
                max_articles_raw = body.get("max_articles")
                max_articles = int(max_articles_raw) if max_articles_raw not in (None, "") else 5
                date_from = str(body.get("date_from") or "").strip() or None
                date_to = str(body.get("date_to") or "").strip() or None

                env_overrides = {
                    "GEMINI_API_KEY": str(body.get("gemini_api_key") or "").strip(),
                    "GROQ_API_KEY": str(body.get("groq_api_key") or "").strip(),
                    "NVIDIA_API_KEY": str(body.get("nvidia_api_key") or "").strip(),
                }
                try:
                    snap = job_manager.start_update(
                        period_days=period_days,
                        date_from=date_from,
                        date_to=date_to,
                        max_articles=max_articles,
                        env_overrides=env_overrides,
                    )
                except RuntimeError as exc:
                    self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self._send_json(HTTPStatus.ACCEPTED, snap)
                return

            if path == "/api/admin/problems/delete-all":
                if not self._require_admin():
                    return
                removed = delete_problems(out_dir=data_path, delete_all=True)
                self._send_json(HTTPStatus.OK, {"deleted_ids": removed, "count": len(removed)})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found"})

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            prefix = "/api/admin/problems/"
            if path.startswith(prefix):
                if not self._require_admin():
                    return
                pid = unquote(path[len(prefix) :]).strip("/")
                if not pid or "/" in pid or ".." in pid:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid problem id"})
                    return
                removed = delete_problems(out_dir=data_path, problem_ids=[pid])
                self._send_json(
                    HTTPStatus.OK,
                    {"deleted": pid in removed, "id": pid, "deleted_ids": removed},
                )
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found"})

    return ThreadingHTTPServer((host, port), SynthesisRequestHandler)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run SynthesisFinder web server with Auth & Admin API.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--site-dir", default="site", help="Static site directory")
    parser.add_argument("--users-file", default=".synthesis_finder_users.json", help="User database file")
    args = parser.parse_args(argv)

    server = create_server(
        host=args.host,
        port=args.port,
        site_dir=args.site_dir,
        users_file=args.users_file,
    )
    logger.info("SynthesisFinder server running at http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
