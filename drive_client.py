import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2 import service_account

load_dotenv()

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _credentials_path() -> str:
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not set.")
    return path


def _credentials():
    return service_account.Credentials.from_service_account_file(
        _credentials_path(),
        scopes=DRIVE_SCOPES,
    )


def _auth_headers(content_type: str | None = None) -> dict:
    credentials = _credentials()
    credentials.refresh(Request())
    headers = {"Authorization": f"Bearer {credentials.token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _request_json(method: str, url: str, body: bytes | None = None, content_type: str | None = None) -> dict:
    request = urllib.request.Request(url, data=body, method=method)
    for key, value in _auth_headers(content_type).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Drive API error {exc.code}: {detail}") from exc


def create_claim_folder(parent_folder_id: str, claim_name: str) -> dict:
    metadata = {
        "name": claim_name,
        "mimeType": FOLDER_MIME,
        "parents": [parent_folder_id],
    }
    query = urllib.parse.urlencode({"supportsAllDrives": "true", "fields": "id,name"})
    url = f"{DRIVE_API_BASE}/files?{query}"
    return _request_json(
        "POST",
        url,
        body=json.dumps(metadata).encode("utf-8"),
        content_type="application/json; charset=UTF-8",
    )


def upload_pdf_to_folder(folder_id: str, filename: str, file_bytes: bytes, mime_type: str = "application/pdf") -> dict:
    metadata = {
        "name": filename,
        "parents": [folder_id],
    }
    boundary = "===============claimsense_boundary==="
    parts = [
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n",
        f"--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n",
    ]
    body = b"".join(part.encode("utf-8") for part in parts) + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    query = urllib.parse.urlencode({"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,name"})
    url = f"{DRIVE_UPLOAD_BASE}/files?{query}"
    return _request_json(
        "POST",
        url,
        body=body,
        content_type=f"multipart/related; boundary={boundary}",
    )


def upload_claim_documents(parent_folder_id: str, claim_name: str, documents: Iterable[dict]) -> dict:
    folder = create_claim_folder(parent_folder_id, claim_name)
    uploaded_files = []

    for document in documents:
        file_result = upload_pdf_to_folder(
            folder["id"],
            document["filename"],
            document["bytes"],
            document.get("mime_type") or "application/pdf",
        )
        uploaded_files.append(file_result)

    return {"folder": folder, "files": uploaded_files}