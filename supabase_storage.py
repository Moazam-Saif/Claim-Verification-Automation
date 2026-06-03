"""
supabase_storage.py

Handles PDF uploads to Supabase Storage.
Replaces Google Drive entirely.

Bucket layout:
    claims/{claim_id}/{filename}

Each file gets a signed URL (valid 7 days) stored alongside the claim record.

Setup required in Supabase dashboard:
    1. Storage → New bucket → name: "claims" → set to PRIVATE
    2. No RLS policies needed for server-side uploads (uses service key)

Design notes:
    - upload_claim_files() accepts raw_docs dicts (with "filename" and "file_bytes")
      rather than file objects. This avoids the stream-exhaustion bug where
      pdf_reader.extract_text_from_bytes() had already consumed the file stream
      before this module could read it.

    - supabase-py v2 sometimes returns error objects instead of raising exceptions.
      The upload response is checked explicitly for this.

    - supabase-py v2 returns a SignedURLResponse dataclass from create_signed_url().
      The URL lives at response.signed_url — NOT response.data["signedUrl"].
      _extract_signed_url() handles all known response shapes safely.
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

    supabase-py v2 returns a SignedURLResponse dataclass with a `signed_url`
    attribute directly on the object. It is NOT a dict and does NOT have a
    .data wrapper — that is the JS SDK shape and does not apply here.

    Fallback chain handles edge cases and future SDK changes gracefully.
    """
    # supabase-py v2: direct attribute (the correct path)
    if hasattr(response, 'signed_url') and response.signed_url:
        return response.signed_url

    # Some intermediate versions wrapped in .data as a dataclass
    if hasattr(response, 'data'):
        data = response.data
        if hasattr(data, 'signed_url') and data.signed_url:
            return data.signed_url
        if isinstance(data, dict):
            return data.get('signedUrl') or data.get('signedURL') or ''

    # Last resort: plain dict
    if isinstance(response, dict):
        return response.get('signedUrl') or response.get('signedURL') or ''

    return ''


def upload_claim_files(claim_id: str, raw_docs: list) -> list:
    """
    Upload documents to Supabase Storage.

    Args:
        claim_id:  UUID string of the claim (used as the folder name)
        raw_docs:  list of dicts with "filename" and "file_bytes" keys,
                   as built in app.py Stage 1. Bytes are used directly —
                   no file streams involved.

    Returns:
        list of dicts:
        [
            {
                "filename":   "01_insurance_claim_form.pdf",
                "path":       "abc-123/01_insurance_claim_form.pdf",
                "signed_url": "https://...supabase.co/storage/v1/object/sign/...",
                "error":      None   # or error string if upload failed
            },
            ...
        ]
    """
    client = _get_client()
    results = []

    for doc in raw_docs:
        filename   = doc["filename"]
        file_bytes = doc["file_bytes"]
        storage_path = f"{claim_id}/{filename}"

        try:
            upload_response = client.storage.from_(BUCKET).upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true"
                }
            )

            # supabase-py v2 sometimes returns an error object instead of raising.
            # Check explicitly so a silent failure doesn't proceed to create_signed_url
            # on a path that was never actually written.
            if hasattr(upload_response, 'error') and upload_response.error:
                raise RuntimeError(f"Upload failed: {upload_response.error}")

            # Generate signed URL valid for 7 days (604800 seconds)
            signed_response = client.storage.from_(BUCKET).create_signed_url(
                path=storage_path,
                expires_in=604800
            )
            signed_url = _extract_signed_url(signed_response)

            results.append({
                "filename":   filename,
                "path":       storage_path,
                "signed_url": signed_url,
                "error":      None
            })

        except Exception as e:
            # Don't crash the pipeline if a single file fails
            results.append({
                "filename":   filename,
                "path":       storage_path,
                "signed_url": None,
                "error":      str(e)
            })

    return results


def get_signed_urls_for_claim(claim_id: str, filenames: list) -> list:
    """
    Regenerate signed URLs for an existing claim's files.
    Called when stored URLs have expired (after 7 days).

    Args:
        claim_id:  UUID string
        filenames: list of filename strings (basename only, not the full path)

    Returns:
        list of { filename, signed_url } dicts
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