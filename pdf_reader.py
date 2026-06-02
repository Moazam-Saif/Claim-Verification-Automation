"""
utils/pdf_reader.py

Extracts clean text from uploaded PDF files using pdfplumber.
Handles: empty files, image-only PDFs, corrupted files, garbled text.

Called once per uploaded file before any agent sees the document.
"""

import pdfplumber
import re
import io


def extract_text(file_obj) -> dict:
    """
    Extract raw text from a PDF file object (from Flask request.files).

    Returns:
        {
            "success":    bool   — whether usable text was extracted
            "text":       str    — full cleaned text (empty string if failed)
            "page_count": int    — number of pages
            "reason":     str    — failure reason if success=False, else None
        }
    """
    try:
        file_bytes = file_obj.read()

        if len(file_bytes) == 0:
            return _fail("Uploaded file is empty.")

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)

            if page_count == 0:
                return _fail("PDF has no pages.")

            pages_text = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    pages_text.append(page_text.strip())

            if not pages_text:
                return _fail(
                    "No text layer detected. This appears to be a scanned image PDF. "
                    "OCR processing is required for this document type."
                )

            full_text = "\n\n".join(pages_text)
            full_text = _clean(full_text)

            if len(full_text.strip()) < 40:
                return _fail(
                    "Extracted text is too short to be a valid document. "
                    "The PDF may be corrupted or contain only images."
                )

            return {
                "success":    True,
                "text":       full_text,
                "page_count": page_count,
                "reason":     None
            }

    except Exception as e:
        return _fail(f"Failed to read PDF: {str(e)}")


def _clean(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[^\x20-\x7E\n\t]', ' ', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def _fail(reason: str) -> dict:
    return {"success": False, "text": "", "page_count": 0, "reason": reason}
