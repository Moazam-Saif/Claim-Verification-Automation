"""
supabase_storage.py

Handles PDF uploads to Supabase Storage.

FIX: The original code tried to read the signed URL from response.data["signedURL"]
     or response.data["signedUrl"] — neither exists in supabase-py v2.
     The Python SDK returns a SignedURLResponse object where the URL is a direct
     attribute: response.signed_url (lowercase, underscore).
     This is completely different from the JS SDK (data.signedUrl) that the
     original code was accidentally ported from.
"""

import os
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in your .env file."
            )
        _client = create_client(url, key)
    return _client


BUCKET = "claims"


def _extract_signed_url(response) -> str:
    """
    Extract the signed URL string from a supabase-py v2 create_signed_url response.

    supabase-py v2 returns a SignedURLResponse dataclass with a `signed_url` attribute.
    This is NOT a dict and does NOT have a `.data` wrapper — that's the JS SDK shape.

    Fallback chain handles any edge-cases or future SDK changes gracefully.
    """
    # supabase-py v2: direct attribute (correct path)
    if hasattr(response, 'signed_url') and response.signed_url:
        return response.signed_url

    # Some intermediate versions wrapped in .data as a dataclass
    if hasattr(response, 'data'):
        data = response.data
        if hasattr(data, 'signed_url') and data.signed_url:
            return data.signed_url
        # dict shape (shouldn't happen in v2 but handle anyway)
        if isinstance(data, dict):
            return data.get('signedUrl') or data.get('signedURL') or ''

    return ''


def upload_claim_files(claim_id: str, files: list) -> list:
    """
    Upload a list of Flask file objects to Supabase Storage.

    Returns list of dicts:
        { "filename", "path", "signed_url", "error" }
    """
    client = _get_client()
    results = []

    for f in files:
        filename = f.filename
        storage_path = f"{claim_id}/{filename}"

        try:
            f.stream.seek(0)
            file_bytes = f.stream.read()

            client.storage.from_(BUCKET).upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true"
                }
            )

            signed_response = client.storage.from_(BUCKET).create_signed_url(
                path=storage_path,
                expires_in=604800   # 7 days
            )
            signed_url = _extract_signed_url(signed_response)

            results.append({
                "filename":   filename,
                "path":       storage_path,
                "signed_url": signed_url,
                "error":      None
            })

        except Exception as e:
            results.append({
                "filename":   filename,
                "path":       storage_path,
                "signed_url": None,
                "error":      str(e)
            })

    return results


def get_signed_urls_for_claim(claim_id: str, filenames: list) -> list:
    """
    Regenerate signed URLs for an existing claim's files (used when stored URLs expire).
    """
    client = _get_client()
    results = []

    for filename in filenames:
        storage_path = f"{claim_id}/{filename}"
        try:
            signed_response = client.storage.from_(BUCKET).create_signed_url(
                path=storage_path,
                expires_in=604800
            )
            signed_url = _extract_signed_url(signed_response)
            results.append({"filename": filename, "signed_url": signed_url})
        except Exception as e:
            results.append({"filename": filename, "signed_url": None, "error": str(e)})

    return results
