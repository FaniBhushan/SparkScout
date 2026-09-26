"""Exercise Streamlit controls without an API key or live source calls."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StreamlitUITests(unittest.TestCase):
    def test_offline_preview_and_deliberate_run(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertIsNone(app.session_state["result"])
        self.assertTrue(app.button[2].disabled)

        app.button[1].click().run(timeout=30)
        self.assertEqual(len(app.error), 0)
        self.assertFalse(app.button[2].disabled)
        self.assertIsNone(app.session_state["result"])

        app.number_input[0].set_value(31).run(timeout=30)
        self.assertTrue(app.button[2].disabled)
        app.button[1].click().run(timeout=30)
        self.assertFalse(app.button[2].disabled)
        app.button[2].click().run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertEqual(app.session_state["result"].status, "completed")
        self.assertEqual(app.session_state["result"].budget_usage.provider_calls,
                         {"frozen_fixture": 2})

    def test_advanced_controls_survive_mode_switch_and_bad_weights_block_preview(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        app.radio[1].set_value("Advanced").run(timeout=30)
        provider = next(widget for widget in app.multiselect if widget.label.startswith("Ready providers"))
        provider.set_value(["frozen_fixture"]).run(timeout=30)
        source_bytes = next(widget for widget in app.number_input
                            if widget.label == "Maximum normalized source bytes")
        source_bytes.set_value(500_000).run(timeout=30)
        app.radio[1].set_value("Simple").run(timeout=30)
        self.assertEqual(app.session_state["ui_values"]["search.provider_ids"], ["frozen_fixture"])
        self.assertEqual(app.session_state["ui_values"]["budgets.max_source_bytes"], 500_000)
        app.radio[1].set_value("Advanced").run(timeout=30)
        provider = next(widget for widget in app.multiselect if widget.label.startswith("Ready providers"))
        self.assertEqual(provider.value, ["frozen_fixture"])
        self.assertEqual(next(widget for widget in app.number_input
                              if widget.label == "Maximum normalized source bytes").value,
                         500_000)

        custom = next(widget for widget in app.checkbox if widget.label == "Use custom weights")
        custom.set_value(True).run(timeout=30)
        app.radio[1].set_value("Simple").run(timeout=30)
        app.radio[1].set_value("Advanced").run(timeout=30)
        self.assertTrue(next(widget for widget in app.checkbox
                             if widget.label == "Use custom weights").value)
        problem = next(widget for widget in app.number_input if widget.label == "Problem value")
        problem.set_value(20).run(timeout=30)
        app.button[1].click().run(timeout=30)
        self.assertTrue(app.button[2].disabled)
        self.assertTrue(any("total 100" in error.value for error in app.error))
        self.assertIsNone(app.session_state["result"])

    def test_upload_terms_are_required_and_new_files_reset_agreement(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        app.radio[0].set_value("Live sources").run(timeout=30)
        uploader = app.file_uploader[0]
        uploader.upload("notes.txt", b"Synthetic user notes", mime_type="text/plain").run(timeout=30)
        agreement = next(item for item in app.checkbox
                         if item.label == "I agree to the upload terms")
        self.assertFalse(agreement.value)
        self.assertIn("not verify a license", " ".join(item.value for item in app.info))

        app.button[1].click().run(timeout=30)
        self.assertTrue(any("Agree to the upload terms" in item.value for item in app.error))
        agreement = next(item for item in app.checkbox
                         if item.label == "I agree to the upload terms")
        agreement.set_value(True).run(timeout=30)
        self.assertEqual(app.session_state["ui_values"]["search.uploads"][0]["filename"],
                         "notes.txt")
        app.button[1].click().run(timeout=30)
        self.assertEqual(len(app.error), 0)
        self.assertIsNotNone(app.session_state["preview"])
        app.file_uploader[0].upload("other.txt", b"Different synthetic notes",
                                    mime_type="text/plain").run(timeout=30)
        self.assertFalse(next(item for item in app.checkbox
                              if item.label == "I agree to the upload terms").value)
        self.assertTrue(app.button[2].disabled)


if __name__ == "__main__":
    unittest.main()
