"""Run-scoped, rights-confirmed local documents; no file bytes are persisted."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Sequence

from src.guardrails import check_privacy
from src.models.run_configuration import UploadedSource
from src.models.scout_query import SourceQuery
from src.models.source_record import RetrievalStatus, SourceRecord


MAX_FILES = 5
MAX_FILE_BYTES = 2_000_000
MAX_PDF_PAGES = 20
MAX_TEXT_CHARS = 20_000


class UserUploadAdapter:
    """Keep raw file bytes out of run JSON; Library may cite extracted chunks."""

    provider_id = "user_upload"

    def __init__(
        self,
        files: Sequence[tuple[str, bytes, str]],
        *,
        rights_confirmed: bool,
    ) -> None:
        if not rights_confirmed:
            raise ValueError("confirm your right to use uploaded content for this run")
        if not files or len(files) > MAX_FILES:
            raise ValueError(f"upload between 1 and {MAX_FILES} files")
        self.manifest: list[UploadedSource] = []
        self.warnings: list[str] = []
        self._records: list[SourceRecord] = []
        seen_names: set[str] = set()
        seen_hashes: set[str] = set()
        for filename, raw, language in files:
            check_privacy(filename)
            if filename in seen_names:
                raise ValueError("uploaded filenames must be unique")
            seen_names.add(filename)
            if not raw or len(raw) > MAX_FILE_BYTES:
                raise ValueError(f"{filename}: file must contain 1–{MAX_FILE_BYTES} bytes")
            suffix = Path(filename).suffix.lower()
            if suffix not in {".txt", ".md", ".pdf"}:
                raise ValueError(f"{filename}: only .txt, .md, and .pdf are supported")
            if suffix == ".pdf":
                text, pages = _pdf_text(raw, filename)
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(f"{filename}: text must be UTF-8") from error
                pages = 0
            text = text.strip()
            self.warnings = list(dict.fromkeys([*self.warnings, *check_privacy(text)]))
            if not text or len(text) > MAX_TEXT_CHARS:
                raise ValueError(f"{filename}: extractable text must be 1–{MAX_TEXT_CHARS} characters")
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen_hashes:
                raise ValueError(f"{filename}: duplicate uploaded content")
            seen_hashes.add(digest)
            receipt = UploadedSource(
                filename=filename, sha256=digest, byte_count=len(raw),
                pdf_pages=pages, language=language, rights_confirmed=True,
            )
            self.manifest.append(receipt)
            self._records.append(SourceRecord(
                source_id=f"upload-{digest[:20]}", provider=self.provider_id,
                source_type="user_document", title=filename,
                captured_at=datetime.now(timezone.utc), query_id="uploaded-documents",
                abstract_or_snippet=text[:2000], language=language,
                full_text=text, content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                license_access_note="User confirmed rights for this run; not independently verified.",
                retrieval_status=RetrievalStatus.SUCCESS,
                provider_record_id=digest,
            ))

    async def search(self, query: SourceQuery) -> list[SourceRecord]:
        if query.provider_id != self.provider_id:
            raise ValueError("query provider does not match user_upload")
        if "user_document" not in query.source_types:
            return []
        full_text_allowed = "licensed_full_text" in query.content_types
        return [
            record.model_copy(update={
                "query_id": query.query_id,
                "full_text": record.full_text if full_text_allowed else None,
                "abstract_or_snippet": record.abstract_or_snippet if full_text_allowed else None,
            })
            for record in self._records[:query.max_results]
        ]


def _pdf_text(raw: bytes, filename: str) -> tuple[str, int]:
    """Reject encrypted, oversize, or image-only PDFs before they enter research."""

    if not raw.startswith(b"%PDF-"):
        raise ValueError(f"{filename}: not a PDF file")
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValueError("PDF uploads require the pypdf dependency") from error

    try:
        reader = PdfReader(BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ValueError(f"{filename}: encrypted PDFs are not supported")
        pages = len(reader.pages)
        if not 1 <= pages <= MAX_PDF_PAGES:
            raise ValueError(f"{filename}: PDF must have 1–{MAX_PDF_PAGES} pages")
        parts = []
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_FILE_BYTES:
                raise ValueError(f"{filename}: PDF page content exceeds the safety limit")
            parts.append(page.extract_text() or "")
        return "\n\n".join(parts), pages
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"{filename}: could not extract PDF text") from error
