# Reliability, checkpoints, and replay

## Starting and resuming

Checkpointing is opt-in through the shared application or CLI. The Streamlit
interface continues to use memory-only runs; it does not expose resume controls.

```sh
python -m src.ui.cli --case evals/cases/development/ai_engineering_capstone_01.json --offline-demo --checkpoint-dir runs/example
python -m src.ui.cli --case evals/cases/development/ai_engineering_capstone_01.json --offline-demo --checkpoint-dir runs/example --resume
```

Use a new directory for a new run. Supply identical input/configuration,
model, scheduling mode, pricing, and adapter settings when resuming.
Add `--frozen-replay` instead of `--resume` to require saved stage outputs;
a missing or invalid stage fails before its model/provider work starts.
Live replay still requires the original provider configuration and credentials
to pass ordinary preflight. Constructing clients/adapters makes no requests.

## Saved state and retention

`src/persistence/` owns the version 1.0 `state.json` envelope, checksums,
fingerprints, stage wrappers, and atomic writes. Each run has one stable ID.
The manifest records hashes of normalized/submitted configuration, code,
prompts, operator configuration, adapter settings, and frozen source snapshots.
An exclusive POSIX file lock prevents concurrent writers. Files are written to a
private temporary file, flushed, and atomically replaced, then the directory is
flushed. This implementation targets local macOS/Linux filesystems.

Checkpoints cover normalization, Scout, Library, the validated join, Critic,
evaluation/ranking, individual proposal drafts and verification audits, and
finalization. Audits are reused only for the same narrative, claims, and evidence.
Valid results
are reused; missing or schema-invalid stage results rerun with their current
dependencies. The retrieval index is rebuilt from Library chunks when needed.
Checksums detect accidental corruption, not intentional tampering by someone
who controls the directory. A corrupted whole-state checksum stops resume
because saved spending cannot be trusted.

Validated stage outputs form a cache restricted to this run and exact inputs.
No cross-run response cache or raw model-response cache is enabled. Replay
uses saved stage results, which also avoids repeating their searches/model calls.
The manifest records cache hits and stage events. Reuse expires 24 hours after
creation. Files remain as local audit records until the user removes the run
directory; expiry does not automatically delete them. `runs/` is ignored by Git.

## Upload privacy

For any run containing uploads, **all stage outputs remain in memory**, including
generated text that might quote an upload. Disk state contains only fingerprints,
budget counters, run identity, and bounded events. Re-upload the identical files
to resume after a restart; stages must be recomputed. Their costs count against
the original allowance. Exhausted runs require an explicit new run. Frozen replay
after restart cannot reconstruct volatile upload stages and fails without calls.

## Budgets and failures

Token/cost reservations and provider attempts are persisted before calls begin.
Reported usage settles the reservation; timeout/cancellation or missing usage
keeps the conservative reservation unavailable. Resume restores spent and reserved
amounts, source bytes, provider attempts, and accumulated active execution time.
Time spent while the process is stopped is excluded. Cache hits do not incur new
provider or model usage. The CLI output exposes reported and reserved usage.

SDK retries are disabled. `--retry-once` enables one application-managed retry
per call for transient connection, timeout, service-unavailable, or rate-limit
errors. Every attempt reserves budget. `Retry-After` is respected; waits longer
than 30 seconds or the remaining runtime are declined. Authentication, quota,
malformed JSON/schema output, and hard budget failures are not retried.

Provider and model failures have typed exceptions. Coordinator errors expose a
stable `code`; malformed schema output is `invalid_output`. Required parallel
branch failure cancels and drains its sibling. Empty retrieval returns explicit
insufficient coverage and skips Critic. Blocking provider HTTP calls already in a
worker thread may finish after cancellation, bounded by their socket timeout;
their attempted request remains charged.

Proposal backfilling reuses the existing ranked candidate pool before making new
research calls. An empty result can trigger one recovery round with separate
`recovery:library`, `recovery:scout`, `recovery:critic`, `recovery:evaluated`, and
`recovery:finalized` checkpoints. Resume reuses these stages under the same input
and code fingerprints and remaining shared budget. This application-level
recovery is separate from transport retries. A recorded recovery outcome exposes
prior gate judgments, draft failures, replacements, and any exhaustion reason.

## Verification

`test_checkpoints.py` covers interrupted resume, replay without model calls,
changed identity, corrupted state, locking, atomic-write failure, and upload
privacy. `test_reliability.py` checks retry accounting and typed failures.
`test_run_equivalence.py` compares complete sequential/parallel outputs on fixed
sources and deterministic model responses, including a score tie and a failed
hard gate. Only run IDs, timestamps, index IDs, mode, and elapsed time are omitted
from comparison. Existing tests cover invalid citations and insufficient coverage.
This establishes scheduling invariants on frozen inputs; live models can vary.

Paid `python -m evals.end_to_end` runs also save checkpoints beside their output
directory by default. Use `--checkpoint-root PATH --resume` with unchanged inputs
and code to continue an interrupted evaluation. Choose a new report directory;
do not overwrite an earlier measurement or reuse checkpoints across code changes.
