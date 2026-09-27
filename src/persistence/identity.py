"""Fingerprint behavior and frozen inputs without retaining credential values."""

from dataclasses import asdict
from pathlib import Path

from .store import digest


def run_identity(prepared, client, adapters, output_limits, mode, pricing, retry_limit):
    root = Path(__file__).resolve().parents[2]
    files = [*sorted((root / "src").rglob("*.py")), *sorted((root / "src/prompts").glob("*.md")),
             *sorted((root / "config").glob("*.json"))]
    code = {str(path.relative_to(root)): path.read_text() for path in files}
    providers = {}
    for name, adapter in adapters.items():
        # Only non-secret adapter properties define retrieval behavior.
        providers[name] = {key: getattr(adapter, key, None) for key in (
            "provider_id", "endpoint", "timeout_seconds", "max_results", "fixture_set")}
        if getattr(adapter, "fixture_dir", None):
            providers[name]["snapshot"] = digest({
                filename: (adapter.fixture_dir / filename).read_text()
                if (adapter.fixture_dir / filename).is_file() else None
                for filename in ("sources.json", "chunks.json")
            })
    return {
        "configuration_sha256": prepared.configuration_checksum,
        "submitted_sha256": digest(prepared.submitted.model_dump(mode="json")),
        "implementation_sha256": digest(code), "providers_sha256": digest(providers),
        "model": getattr(client, "model", type(client).__module__ + "." + type(client).__qualname__),
        "output_limits": asdict(output_limits), "mode": mode,
        "pricing": asdict(pricing) if pricing else None, "retry_limit": retry_limit,
    }
