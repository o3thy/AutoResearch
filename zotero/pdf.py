import hashlib
import re
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from rr.extract import normalize_doi


class PDFError(ValueError):
    pass


def canonical(value):
    return re.sub(r"[\W_]+", "", value or "", flags=re.UNICODE).casefold()


def inspect_pdf(content, title=None, doi=None, explicit_mapping=False):
    if not content.lstrip().startswith(b"%PDF-") or b"%%EOF" not in content[-4096:]:
        raise PDFError("Not a complete PDF (HTML, partial download, or missing PDF markers)")
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise PDFError("Password-protected PDF")
        if not reader.pages:
            raise PDFError("PDF has no pages")
        first = reader.pages[0].extract_text() or ""
        metadata = reader.metadata or {}
        metadata_title = str(metadata.get("/Title", ""))
        # References on later pages are not evidence of this document's identity.
        front = first[:16000]
        expected = normalize_doi(doi)
        extracted = {normalize_doi(x.rstrip(".,;:)")) for x in re.findall(r"10\.\d{4,9}/[^\s<>]+", front, re.I)}
        title_match = bool(title and ((len(canonical(title)) >= 12 and canonical(title) in canonical(front)) or
                                     canonical(title) == canonical(metadata_title)))
        doi_match = bool(expected and expected in extracted)
        declared = {normalize_doi(x.rstrip(".,;:)")) for x in re.findall(
            r"\bdoi\s*:?\s*(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s<>]+)", front[:4000], re.I)}
        if expected and declared and expected not in declared:
            raise PDFError("The PDF explicitly identifies a different DOI")
        if title_match:
            identity = "title_and_doi" if doi_match else "title"
        elif explicit_mapping and not front.strip():
            identity = "user_mapping_scanned_pdf"
        else:
            raise PDFError("PDF identity is unverified: expected title was not found on the first page or in metadata")
        return {"pages": len(reader.pages), "identity": identity,
                "doi_on_first_page": doi_match, "sha256": hashlib.sha256(content).hexdigest(),
                "md5": hashlib.md5(content).hexdigest(), "bytes": len(content)}
    except PDFError:
        raise
    except Exception as exc:
        raise PDFError(f"PDF parser rejected the file: {type(exc).__name__}") from exc


def inspect_file(path, title, doi=None, explicit_mapping=False):
    return inspect_pdf(Path(path).read_bytes(), title, doi, explicit_mapping)
