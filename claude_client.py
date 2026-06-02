"""
utils/claude_client.py

Single wrapper around the Anthropic SDK used by all agents.
All agents call this. None of them touch the SDK directly.

Responsibilities:
- Make the API call
- Parse JSON from the response (handles markdown fences if Claude adds them despite instructions)
- Retry on transient failures
- Return a consistent result envelope: {ok, data} or {ok, error}
"""

import json
import re
import time
import os
import random

# This module provides a thin adapter named `call_claude(...)` so existing
# agents don't need to change imports. Under the hood it uses the
# `google.generativeai` SDK and the Gemini model specified by `GEMINI_MODEL`.

try:
    import google.generativeai as genai
except Exception:
    genai = None

# Configure at import time if possible
_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# Accept multiple env var names for the API key to match .env.example
_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
if genai and _API_KEY:
    try:
        genai.configure(api_key=_API_KEY)
    except Exception:
        # defer failures to runtime calls
        pass


def call_claude(system_prompt: str, user_prompt: str,
                max_tokens: int = 1200, retries: int = 2) -> dict:
    """
    Call Claude and return parsed JSON.

    Returns:
        {"ok": True,  "data": <parsed dict>}
        {"ok": False, "error": <message>, "raw": <text if available>}
    """
    last_error = None

    # Basic validation
    if not _API_KEY:
        return {"ok": False, "error": "GOOGLE_API_KEY not set", "raw": ""}

    if genai is None:
        return {"ok": False, "error": "google.generativeai SDK not installed", "raw": ""}

    for attempt in range(retries + 1):
        try:
            # Create a model instance per-call (simple, explicit)
            model = genai.GenerativeModel(model_name=_MODEL_NAME, system_instruction=system_prompt)
            response = model.generate_content(user_prompt)

            # Try a few ways to extract raw text depending on SDK shape
            raw = None
            if hasattr(response, 'text'):
                raw = response.text
            elif hasattr(response, 'content'):
                raw = response.content
            else:
                # fallback to string
                raw = str(response)

            raw = raw.strip()
            # Strip accidental fences
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
            # Generic retryable behaviour for network/SDK glitches
            last_error = f"Error calling Gemini: {str(e)}"
            if attempt < retries:
                time.sleep((2 ** attempt) + random.random())
                continue

    return {"ok": False, "error": last_error or "Unknown error", "raw": ""}


def _parse_json(text: str) -> dict | None:
    """
    Parse JSON from Claude's response.
    Handles ```json ... ``` fences in case Claude adds them despite instructions.
    """
    # Direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    stripped = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped, flags=re.MULTILINE).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Last resort: find first complete {...} block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None
