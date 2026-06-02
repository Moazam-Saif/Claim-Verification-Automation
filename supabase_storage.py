"""
supabase_storage.py

Handles PDF uploads to Supabase Storage.
Replaces Google Drive entirely.

Bucket layout:
    claims/{claim_id}/{filename}

Each file gets a signed URL (valid 7 days) stored alongside the claim record.
Public URLs are also generated so the admin panel can link directly to files.

Setup required in Supabase dashboard:
    1. Storage → New bucket → name: "claims" → set to PRIVATE
    2. No RLS policies needed for server-side uploads (uses service key)
"""

import os
import io
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")  # Service key, not anon key
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in your .env file."
            )
        _client = create_client(url, key)
    return _client


BUCKET = "claims"


def upload_claim_files(claim_id: str, files: list) -> list:
    """
    Upload a list of Flask file objects to Supabase Storage.

    Args:
        claim_id:  UUID string of the claim (used as the folder name)
        files:     list of werkzeug FileStorage objects from request.files

    Returns:
        list of dicts:
        [
            {
                "filename":   "01_insurance_claim_form.pdf",
                "path":       "claims/abc-123/01_insurance_claim_form.pdf",
                "signed_url": "https://...supabase.co/storage/v1/object/sign/...",
                "error":      None   # or error message string if upload failed
            },
            ...
        ]
    """
    client = _get_client()
    results = []

    for f in files:
        filename = f.filename
        storage_path = f"{claim_id}/{filename}"

        try:
            # Read bytes — file cursor may already be at start from pdf_reader,
            # so seek back to be safe
            f.stream.seek(0)
            file_bytes = f.stream.read()

            # Upload to Supabase Storage
            # upsert=True overwrites if the same filename was uploaded before
            client.storage.from_(BUCKET).upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true"
                }
            )

            # Generate a signed URL valid for 7 days (604800 seconds)
            signed = client.storage.from_(BUCKET).create_signed_url(
                path=storage_path,
                expires_in=604800
            )
            signed_url = signed.get("signedURL") or signed.get("signedUrl") or ""

            results.append({
                "filename":   filename,
                "path":       storage_path,
                "signed_url": signed_url,
                "error":      None
            })

        except Exception as e:
            # Don't crash the pipeline if a single upload fails
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
    Used by the admin panel when URLs have expired.

    Args:
        claim_id:  UUID string
        filenames: list of filename strings (just the basename, not the full path)

    Returns:
        list of { filename, signed_url } dicts
    """
    client = _get_client()
    results = []

    for filename in filenames:
        storage_path = f"{claim_id}/{filename}"
        try:
            signed = client.storage.from_(BUCKET).create_signed_url(
                path=storage_path,
                expires_in=604800
            )
            signed_url = signed.get("signedURL") or signed.get("signedUrl") or ""
            results.append({"filename": filename, "signed_url": signed_url})
        except Exception as e:
            results.append({"filename": filename, "signed_url": None, "error": str(e)})

    return results
