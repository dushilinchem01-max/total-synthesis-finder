"""Multi-provider free-tier LLM clients (Gemini, Groq, NVIDIA NIM)."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails or no provider is available."""


@dataclass(frozen=True)
class Attachment:
    """Binary multimodal attachment (PDF, PNG, JPEG, etc.)."""

    data: bytes
    mime_type: str = "application/pdf"


def extract_json_from_text(text: str) -> Any:
    """Parse JSON from an LLM response, stripping markdown code fences if present."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: locate outermost JSON object or array
        start_obj = cleaned.find("{")
        start_arr = cleaned.find("[")
        candidates = [idx for idx in (start_obj, start_arr) if idx != -1]
        if not candidates:
            raise
        start = min(candidates)
        end_char = "}" if cleaned[start] == "{" else "]"
        end = cleaned.rfind(end_char)
        if end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


class GeminiClient:
    """Google AI Studio / Gemini REST API client supporting text & multimodal PDF/image."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.fallback_models = (
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-flash-lite-latest",
        )
        self.timeout = timeout
        self._http_client = http_client

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        *,
        attachments: list[Attachment] | None = None,
        system_prompt: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> str:
        """Call Gemini generateContent endpoint and return the response text."""
        if not self.is_configured:
            raise LLMError("GEMINI_API_KEY is not set.")

        parts: list[dict[str, Any]] = []
        for att in attachments or []:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": att.mime_type,
                        "data": base64.b64encode(att.data).decode("ascii"),
                    }
                }
            )
        parts.append({"text": prompt})

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature},
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        models_to_try: list[str] = []
        for candidate in (self.model, *self.fallback_models):
            if candidate and candidate not in models_to_try:
                models_to_try.append(candidate)

        params = {"key": self.api_key}
        close_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=self.timeout)
        last_error: Exception | None = None
        data: dict[str, Any] | None = None
        try:
            for model_name in models_to_try:
                url = f"{self.BASE_URL}/{model_name}:generateContent"
                try:
                    resp = client.post(url, params=params, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPError as exc:
                    last_error = exc
                    continue
        finally:
            if close_client:
                client.close()

        if data is None:
            raise LLMError(f"Gemini request failed across models {models_to_try}: {last_error}") from last_error

        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"Gemini returned no candidates: {data}")
        content_parts = candidates[0].get("content", {}).get("parts", [])
        text_chunks = [p.get("text", "") for p in content_parts if "text" in p]
        result = "".join(text_chunks).strip()
        if not result:
            raise LLMError(f"Gemini returned empty text: {data}")
        return result


class OpenAICompatClient:
    """OpenAI-compatible chat completions client (used for Groq and NVIDIA NIM)."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._http_client = http_client

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> str:
        """Call chat/completions endpoint and return assistant message text."""
        if not self.is_configured:
            raise LLMError(f"{self.name} API key is not set.")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        close_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name} request failed: {exc}") from exc
        finally:
            if close_client:
                client.close()

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name} returned no choices: {data}")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise LLMError(f"{self.name} returned empty content: {data}")
        return str(content).strip()


def create_groq_client(
    api_key: str | None = None,
    model: str | None = None,
    http_client: httpx.Client | None = None,
) -> OpenAICompatClient:
    """Create a Groq client using GROQ_API_KEY."""
    return OpenAICompatClient(
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key if api_key is not None else os.getenv("GROQ_API_KEY", ""),
        model=model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        http_client=http_client,
    )


def create_nvidia_client(
    api_key: str | None = None,
    model: str | None = None,
    http_client: httpx.Client | None = None,
) -> OpenAICompatClient:
    """Create an NVIDIA NIM client using NVIDIA_API_KEY."""
    return OpenAICompatClient(
        name="NVIDIA NIM",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key if api_key is not None else os.getenv("NVIDIA_API_KEY", ""),
        model=model or os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"),
        http_client=http_client,
    )


class MultiProviderLLM:
    """Routes fast text tasks across Groq -> NVIDIA -> Gemini, and multimodal tasks to Gemini."""

    def __init__(
        self,
        *,
        gemini: GeminiClient | None = None,
        groq: OpenAICompatClient | None = None,
        nvidia: OpenAICompatClient | None = None,
    ) -> None:
        self.gemini = gemini or GeminiClient()
        self.groq = groq or create_groq_client()
        self.nvidia = nvidia or create_nvidia_client()

    def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> str:
        """Run text generation trying Groq, then NVIDIA NIM, then Gemini."""
        errors: list[str] = []

        for client in (self.groq, self.nvidia):
            if client.is_configured:
                try:
                    return client.generate_text(
                        prompt,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        temperature=temperature,
                    )
                except LLMError as exc:
                    errors.append(str(exc))

        if self.gemini.is_configured:
            try:
                return self.gemini.generate(
                    prompt,
                    system_prompt=system_prompt,
                    json_mode=json_mode,
                    temperature=temperature,
                )
            except LLMError as exc:
                errors.append(str(exc))

        if not errors:
            raise LLMError(
                "No LLM API key configured. Set GROQ_API_KEY, NVIDIA_API_KEY, or GEMINI_API_KEY."
            )
        raise LLMError("All configured text LLM providers failed: " + "; ".join(errors))

    def generate_multimodal(
        self,
        prompt: str,
        attachments: list[Attachment],
        *,
        system_prompt: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> str:
        """Run multimodal generation (PDF/images + text) via Gemini."""
        return self.gemini.generate(
            prompt,
            attachments=attachments,
            system_prompt=system_prompt,
            json_mode=json_mode,
            temperature=temperature,
        )
