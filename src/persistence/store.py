"""Atomic, checksummed snapshots with an exclusive writer and bounded retention."""

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import time
from uuid import uuid4

from src.guardrails import check_privacy
from src.runtime.failures import failure_code


class CheckpointError(RuntimeError):
    code = "checkpoint_invalid"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class RunStore:
    """One local run; caches never cross run directories or configuration hashes.

    Upload-derived outputs stay in a volatile dictionary. On process restart the
    same uploads must be supplied again and work reruns against the saved budget.
    """

    def __init__(self, directory, identity: dict, *, resume=False, uploads=False,
                 frozen=False, tracer=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "state.json"
        self.tracer = tracer
        self.volatile = uploads
        self.frozen = frozen
        self.memory = {}
        self.lock = (self.directory / ".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if resume:
                wrapper = json.loads(self.path.read_text())
                self.state = wrapper["payload"]
                if wrapper["sha256"] != digest(self.state):
                    raise CheckpointError("checkpoint checksum mismatch; budget cannot be trusted")
                if self.state["version"] != "1.0" or self.state["identity"] != identity:
                    raise CheckpointError("checkpoint inputs, code, model, or configuration changed")
                if self.state["expires_at"] <= time():
                    raise CheckpointError("checkpoint expired after 24 hours")
                if self.state["uploads_memory_only"] != uploads:
                    raise CheckpointError("upload retention policy changed")
            else:
                if self.path.exists():
                    raise CheckpointError("run already exists; use resume or a new directory")
                if frozen:
                    raise CheckpointError("frozen replay requires an existing run")
                self.state = {
                    "version": "1.0", "run_id": uuid4().hex, "identity": identity,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": time() + 86400, "uploads_memory_only": uploads,
                    "retention": "24h reuse; user removes local directory", "budget": None,
                    "stages": {}, "events": [], "cache_hits": 0,
                }
                self.flush()
        except BaseException:
            self.lock.close()
            raise

    @property
    def run_id(self):
        return self.state["run_id"]

    def flush(self):
        """Replace one file only after both payload and budget have reached disk."""
        payload = {"sha256": digest(self.state), "payload": self.state}
        fd, name = tempfile.mkstemp(prefix=".state-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, allow_nan=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def save_budget(self, values):
        self.state["budget"] = values
        self.flush()

    def event(self, stage, event):
        if self.volatile and stage.startswith("proposal:"):
            stage = "proposal"
        self.state["events"] = [*self.state["events"][-199:], {"stage": stage, "event": event}]
        if self.tracer:
            self.tracer.event(stage, event)

    def read(self, stage, inputs, model):
        key = digest(inputs)
        records = self.memory if self.volatile else self.state["stages"]
        entry = records.get(stage)
        if (isinstance(entry, dict) and entry.get("input_sha256") == key
                and "value" in entry and entry.get("sha256") == digest(entry["value"])):
            try:
                result = model.model_validate(entry["value"])
            except ValueError:
                result = None
            if result is not None:
                self.state["cache_hits"] += 1
                self.event(stage, "cache_hit")
                self.flush()
                return result
        if self.frozen:
            raise CheckpointError(f"frozen replay has no valid {stage} checkpoint")
        return None

    def write(self, stage, inputs, result):
        value = result.model_dump(mode="json")
        check_privacy(value)
        entry = {"input_sha256": digest(inputs), "sha256": digest(value), "value": value}
        records = self.memory if self.volatile else self.state["stages"]
        records[stage] = entry
        self.event(stage, "checkpoint_saved")
        self.flush()

    async def run_stage(self, stage, inputs, model, operation):
        cached = self.read(stage, inputs, model)
        if cached is not None:
            return cached
        try:
            result = model.model_validate(await operation())
        except BaseException as error:
            self.event(stage, failure_code(error))
            self.flush()
            raise
        self.write(stage, inputs, result)
        return result

    def close(self):
        self.memory.clear()
        self.lock.close()
