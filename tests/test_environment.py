"""Use synthetic files, never developer credentials, to test local loading."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.runtime.environment import load_local_environment


class EnvironmentTests(unittest.TestCase):
    def test_quotes_literal_values_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('OPENAI_API_KEY="fixture-key"\nTAVILY_API_KEY="literal-${HOME}"\n')
            with patch("src.runtime.environment.ENV_FILE", path), patch.dict(
                os.environ, {"OPENAI_API_KEY": "deployment-value"}, clear=True
            ):
                load_local_environment()
                self.assertEqual(os.environ["OPENAI_API_KEY"], "deployment-value")
                self.assertEqual(os.environ["TAVILY_API_KEY"], "literal-${HOME}")

    def test_missing_file_is_harmless(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("src.runtime.environment.ENV_FILE", Path(directory) / ".env"):
                load_local_environment()
