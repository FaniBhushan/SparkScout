"""User uploads are optional, bounded, reviewed, and omitted from exported evidence."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.adapters.user_upload import UserUploadAdapter
from src.application import run_prepared_research
from src.demo import OfflineDemoClient
from src.models import (
    BudgetSelection,
    InputRequest,
    SearchConfiguration,
    SubmittedRunConfiguration,
)
from src.preflight import prepare_run
from src.observability import RunTracer


def _adapter(count: int = 3) -> UserUploadAdapter:
    return UserUploadAdapter(
        [
            (f"notes-{number}.txt", f"PRIVATE_UPLOAD_TEXT_{number} ".encode() + b"Capstone context and evaluation notes.", "en")
            for number in range(count)
        ],
        rights_confirmed=True,
    )


def _synthetic_pdf() -> bytes:
    """Build a tiny, original text PDF in memory; no licensed fixture is checked in."""

    text = b"BT /F1 12 Tf 72 100 Td (Synthetic PDF capstone notes) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n"
        + text + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    pdf += (f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n").encode()
    return pdf


def _submitted(adapter: UserUploadAdapter, **search_values) -> SubmittedRunConfiguration:
    return SubmittedRunConfiguration(
        request=InputRequest(
            domain="AI engineering", time_limit_days=30,
            desired_candidate_count=1, finalist_count=1,
        ),
        search=SearchConfiguration(
            provider_ids=["user_upload"], uploads=adapter.manifest,
            **search_values,
        ),
    )


class UploadValidationTests(unittest.TestCase):
    def test_rights_confirmation_is_required(self):
        with self.assertRaisesRegex(ValueError, "confirm your right"):
            UserUploadAdapter([("notes.txt", b"some notes", "en")], rights_confirmed=False)
        with self.assertRaisesRegex(ValueError, "duplicate uploaded content"):
            UserUploadAdapter([
                ("first.txt", b"same content", "en"),
                ("second.txt", b"same content", "en"),
            ], rights_confirmed=True)

    def test_preflight_binds_file_hashes_and_operator_budgets(self):
        adapter = _adapter()
        prepared = prepare_run(_submitted(adapter, language="en"), {"user_upload": adapter})
        self.assertEqual(prepared.search.upload_sha256["notes-0.txt"], adapter.manifest[0].sha256)
        self.assertEqual(prepared.search.language, "en")
        self.assertNotIn("PRIVATE_UPLOAD_TEXT", prepared.model_dump_json())

        changed = _adapter(2)
        with self.assertRaisesRegex(ValueError, "receipts do not match"):
            prepare_run(_submitted(adapter), {"user_upload": changed})
        with self.assertRaisesRegex(ValueError, "PDF pages exceed"):
            with patch.object(adapter.manifest[0], "pdf_pages", 11):
                prepare_run(_submitted(adapter), {"user_upload": adapter})
        with self.assertRaisesRegex(ValueError, "source-byte budget"):
            prepare_run(SubmittedRunConfiguration(
                **{
                    **_submitted(adapter).model_dump(mode="python"),
                    "budgets": BudgetSelection(max_source_bytes=10),
                }
            ), {"user_upload": adapter})

    def test_document_formats_and_language_are_constrained(self):
        with self.assertRaisesRegex(ValueError, "only .txt, .md, and .pdf"):
            UserUploadAdapter([("script.py", b"print(1)", "en")], rights_confirmed=True)
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            UserUploadAdapter([("notes.txt", b"\xff", "en")], rights_confirmed=True)
        adapter = _adapter()
        with self.assertRaisesRegex(ValueError, "languages do not match"):
            prepare_run(_submitted(adapter, language="de"), {"user_upload": adapter})
        with self.assertRaisesRegex(ValueError, "require the full-text content type"):
            prepare_run(_submitted(adapter, content_types=["metadata"]),
                        {"user_upload": adapter})
        with self.assertRaisesRegex(ValueError, "not a PDF file"):
            UserUploadAdapter([("broken.pdf", b"not a PDF", "en")], rights_confirmed=True)

    def test_pdf_text_is_extracted_and_counted(self):
        adapter = UserUploadAdapter(
            [("synthetic.pdf", _synthetic_pdf(), "en")], rights_confirmed=True
        )
        self.assertEqual(adapter.manifest[0].pdf_pages, 1)
        self.assertIn("Synthetic PDF capstone notes", adapter._records[0].full_text)


class UploadRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_text_reaches_library_but_not_downloadable_result(self):
        adapter = _adapter()
        prepared = prepare_run(_submitted(adapter), {"user_upload": adapter})
        result = await run_prepared_research(
            prepared, OfflineDemoClient(), {"user_upload": adapter}
        )
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.library.chunks)
        self.assertTrue(all(chunk.text_redacted for chunk in result.library.chunks))
        self.assertTrue(all(source.abstract_or_snippet is None for source in result.source_manifest))
        self.assertNotIn("PRIVATE_UPLOAD_TEXT", result.model_dump_json())
        self.assertEqual(result.prepared_run.search.upload_sha256,
                         {item.filename: item.sha256 for item in adapter.manifest})

    async def test_trace_contains_no_uploaded_text(self):
        adapter = _adapter()
        prepared = prepare_run(_submitted(adapter), {"user_upload": adapter})
        with tempfile.TemporaryDirectory() as directory:
            tracer = RunTracer("upload-test", log_dir=Path(directory), console=False)
            try:
                await run_prepared_research(
                    prepared, OfflineDemoClient(), {"user_upload": adapter}, tracer=tracer
                )
            finally:
                tracer.close()
            trace = tracer.trace_path.read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_UPLOAD_TEXT", trace)
        self.assertNotIn("Capstone context and evaluation notes", trace)


if __name__ == "__main__":
    unittest.main()
