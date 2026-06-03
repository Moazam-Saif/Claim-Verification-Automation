"""
claude_client.py

Wrapper around Vertex AI Gemini via the unified google-genai SDK.
Auth: GCP_SERVICE_ACCOUNT_JSON env var (full JSON string, not a file path).
Required env vars: GCP_SERVICE_ACCOUNT_JSON, GOOGLE_CLOUD_LOCATION (optional, defaults us-central1)
All agents call call_claude() — nothing else changes.
"""

import json
import os
import re
import time
import random

try:
    from google import genai
    from google.genai import types
    from google.oauth2 import service_account
except ImportError:
    genai = None

_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    if genai is None:
        raise RuntimeError("google-genai SDK not installed.")

    raw_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if not raw_json:
        raise RuntimeError("GCP_SERVICE_ACCOUNT_JSON env var is not set.")

    service_account_info = json.loads(raw_json)

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )

    _client = genai.Client(
    enterprise=True,        # current
    project=service_account_info["project_id"],
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    credentials=credentials
)

    return _client


def call_claude(system_prompt: str, user_prompt: str,
                max_tokens: int = 1200, retries: int = 2) -> dict:
    last_error = None

    for attempt in range(retries + 1):
        try:
            client = _get_client()

            response = client.models.generate_content(
                model=_MODEL_NAME,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=max_tokens,
                )
            )

            raw = response.text.strip()

            if raw.startswith("```"):
                parts = raw.split("```")
                if len(parts) >= 2:
                    raw = parts[1]
                    if raw.startswith("json"):
                        raw = raw[4:]

            parsed = _parse_json(raw)
            if parsed is None:
                last_error = f"Response was not valid JSON. Raw: {raw[:300]}"
                if attempt < retries:
                    time.sleep((2 ** attempt) + random.random())
                continue

            return {"ok": True, "data": parsed}

        except Exception as e:
            last_error = f"Vertex AI error: {str(e)}"
            if attempt < retries:
                time.sleep((2 ** attempt) + random.random())

    return {"ok": False, "error": last_error or "Unknown error", "raw": ""}


def _parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    stripped = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped, flags=re.MULTILINE).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None