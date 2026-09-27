"""Explicit local credential loading for application entry points."""

from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_local_environment() -> None:
    """Load only the repository's .env, preserving deployment-provided values.

    Disable interpolation so credential characters are kept literal. This does
    not log values, search parent folders, or run on ordinary module imports.
    PYTHON_DOTENV_DISABLED=1 disables local loading for CI and offline tests.
    """
    load_dotenv(ENV_FILE, override=False, interpolate=False)
