"""Streamlit launch file; interface implementation lives in src.ui."""

from src.ui.app import main
from src.runtime.environment import load_local_environment


if __name__ == "__main__":
    load_local_environment()
    main()
