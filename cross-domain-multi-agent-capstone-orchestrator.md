# Cross-Domain Multi-Agent Capstone Orchestrator — Requirements

**Status:** Proposed for design review  
**Version:** 1.2  
**Date:** 23 September 2026  
**Source:** Requirements distilled from `cross_domain_agent_transcript.md`. Statements in the transcript about performance, quality, or cost are hypotheses until measured.

## 1. Product summary

The system helps a student discover and evaluate capstone-project ideas in a user-selected academic or technical domain. It must work across domains such as computer science, mathematics, robotics, engineering, life sciences, medicine, and social science without requiring a permanent vector database for every field.

The target design is a bounded fork–join workflow:

```text
User constraints
      |
      v
Deterministic coordinator
      |
      +-------------------------+
      |                         |
      v                         v
Scout worker                Library worker
discover candidate ideas    collect broad domain evidence
      |                         |
      +------------+------------+
                   |
                   v
             validated join
                   |
                   v
              Critic worker
       retrieve evidence per candidate,
       score, cite, and state uncertainty
                   |
                   v
          deterministic final selection
                   |
                   v
        top three capstone proposals
```

The Scout and Library workers run concurrently because both depend only on the original request. The Critic may start only after both required outputs pass validation. A deterministic coordinator—not a worker agent—owns shared state, budgets, retries, stage transitions, ranking, checkpoints, and final selection.

## 2. Problem statement

Students can find many generic project lists, but it is difficult to identify ideas that are simultaneously relevant to their interests, grounded in current work, sufficiently novel, technically substantial, feasible with available data and tools, and achievable within their time and skill constraints.

A static, universal vector database is not suitable for the first version: its scope is unbounded, its contents become stale, provenance is difficult to preserve, and ingestion cost is paid even for domains no user requests. Conversely, collecting evidence only for ideas already proposed by the Scout risks confirmation bias. The system therefore needs just-in-time, broad-domain evidence collection that is independent of the Scout's candidate list and is used later to challenge each candidate.

## 3. Goals and success definition

### 3.1 Goals

1. Accept a domain, interests, and delivery constraints in a structured request.
2. Discover a diverse set of candidate capstone ideas from current opportunity signals.
3. Independently collect a bounded evidence landscape for the requested domain and interests.
4. Build an isolated, temporary retrieval index for the run.
5. Evaluate every candidate against retrieved evidence and a configurable rubric.
6. Return exactly three traceable, scoped proposals when at least three candidates pass the hard gates.
7. Demonstrate whether parallel orchestration improves latency without reducing output quality, determinism, or safety.
8. Record latency, retrieval quality, constraint adherence, token usage, and estimated cost for each run.
9. Provide a Streamlit interface in which users can configure search through either a simple mode or an advanced mode.

### 3.2 Success definition

The MVP is successful when it completes a reproducible run in at least three distinct domain families, produces grounded and schema-valid candidate evaluations, preserves a citation chain from every material claim to a captured source, and supports an honest A/B comparison between the sequential baseline and parallel target architecture.

All numeric thresholds in this document are acceptance targets or evaluation hypotheses until a dated run reports measured results.

## 4. Non-goals

The first version will not:

- ingest all academic knowledge or maintain one permanent cross-domain corpus;
- download large collections of full-text papers by default;
- claim that an idea is globally novel or scientifically valid;
- autonomously contact researchers, publish content, submit applications, or purchase API access;
- execute code, instructions, or links found in retrieved content;
- allow workers to modify shared state, change the rubric, or select winners;
- recursively spawn agents;
- silently replace missing evidence with model knowledge;
- provide a production-grade, multi-user web platform; the first version uses a local Streamlit interface;
- report synthetic fixtures as real-world evaluation results.

## 5. Users and primary workflow

The primary user is a student or small student team choosing a capstone topic under a fixed deadline. A reviewer or mentor is a secondary user who needs to inspect the evidence, design choice, evaluation, and failure analysis.

### 5.1 Required input

```json
{
  "domain": "Robotics",
  "interests": ["agriculture", "computer vision"],
  "skill_level": "intermediate",
  "team_size": 2,
  "time_limit_days": 30,
  "available_resources": ["laptop", "open-source software"],
  "excluded_topics": [],
  "data_constraints": ["public or research-use data"],
  "desired_candidate_count": 12,
  "finalist_count": 3,
  "search_configuration": {
    "mode": "simple",
    "preset": "balanced",
    "source_types": ["scholarly_article", "official_dataset", "code_repository"],
    "custom_instructions": "Prefer recent sources and do not use blogs."
  },
  "evaluation_configuration": {
    "rubric_preset": "balanced",
    "custom_instructions": "Feasibility is more important than novelty."
  }
}
```

`domain` and `time_limit_days` are mandatory. The implementation must declare defaults for omitted optional fields and include those resolved defaults in the run record.

The request may originate as structured form input, natural language, or a combination of both. Explicit form values take precedence over values deduced from natural language. The user must be shown the resolved request and search configuration before a run when deduction is ambiguous or materially changes source selection.

### 5.2 Required output

Each final proposal must include:

- title and one-sentence problem statement;
- target user or beneficiary;
- proposed artifact or research outcome;
- why the problem matters;
- evidence-backed gap or differentiation claim;
- scoped MVP and explicit non-goals;
- required data, tools, and access assumptions;
- technical approach and at least one alternative;
- feasibility, novelty, technical-depth, evidence-quality, and constraint-fit scores;
- risks, unknowns, and the first kill test;
- evaluation plan with objective and qualitative metrics;
- source citations traceable to stored source receipts.

The run must also produce the full candidate list, the scored candidate matrix, rejection reasons, source manifest, orchestration trace, usage/cost report, and failure log.

## 6. Approaches to compare

The course requirement to compare at least two approaches will be satisfied with the following controlled comparison.

### Approach A — sequential baseline

One coordinator performs the same bounded Scout task, then the same Library task, then invokes the Critic. It uses the same providers, queries, corpus limits, models, prompts, retrieval settings, scoring rubric, and output schemas as Approach B. This is the simple baseline and must be implemented first.

### Approach B — parallel fork–join target

The coordinator launches the Scout and Library workers concurrently, waits for both validated results, and then invokes the Critic. The workers do not converse and receive only the context required for their task.

### Decision rule

Approach B is the intended production design only if it reduces median or p95 pre-Critic latency on the frozen evaluation set and does not regress:

- output schema validity;
- candidate coverage and diversity;
- retrieval relevance or citation correctness;
- final ranking determinism;
- constraint adherence;
- failure rate; or
- cost beyond the configured tolerance.

If the comparison does not establish a meaningful benefit, the system must retain Approach A and document the negative result. A secondary retrieval ablation—Critic with retrieved evidence versus Critic without retrieved evidence—should be run if time permits, but it does not replace the required A/B orchestration comparison.

## 7. Functional requirements

### FR-01 — Request validation

The coordinator shall validate the request before starting work. Invalid or contradictory constraints must produce actionable errors. The normalized request and its checksum shall be stored in the run manifest.

### FR-02 — Domain routing

The system shall map the request to a configurable set of source adapters. Routing shall support multiple sources per domain and a documented fallback path. Provider selection must not be hard-coded into worker prompts.

If no suitable source is configured or available, the system shall report insufficient evidence rather than inventing results.

### FR-03 — Scout worker

The Scout shall:

1. derive bounded search queries from the complete user request;
2. search configured web, community, project, or research-discovery sources;
3. return the configured number of distinct candidate ideas;
4. attach evidence receipts to observed problems, demand signals, and inspiration;
5. return concise structured records rather than full pages; and
6. avoid scoring or selecting the final winner.

Candidate deduplication shall consider semantic overlap, target user, problem, and proposed outcome—not titles alone.

### FR-04 — Library worker

The Library shall independently use the original domain, interests, and constraints, not the Scout's candidate list, to collect a broad evidence landscape. Its query plan should cover:

- recent methods and applications;
- limitations and future-work statements;
- datasets and access conditions;
- tools, simulators, APIs, and hardware assumptions;
- benchmarks and evaluation methods;
- saturated or well-solved areas; and
- safety, ethics, or regulatory constraints where applicable.

The default corpus shall favor metadata and abstracts. Full text may be fetched only when licensed, needed, and within the configured size, request, and time budgets.

### FR-05 — Source capture and normalization

Every captured item shall be converted to a `SourceRecord` containing at least:

```text
source_id, provider, source_type, title, authors/owner,
published_at, captured_at, canonical_url, query_id,
domain_tags, abstract_or_snippet, license/access note,
content_hash, and retrieval status
```

Duplicate records shall be merged deterministically using stable identifiers or canonical URL plus content hash. Conflicting metadata must be preserved and surfaced.

### FR-06 — Temporary retrieval index

After normalization, the Library shall create a run-scoped vector or hybrid retrieval index. The index shall:

- be isolated by run ID;
- contain source and chunk identifiers in metadata;
- use a recorded embedding model and version;
- support deterministic top-k retrieval where the backend permits;
- enforce configured chunk, overlap, corpus, and index-size limits; and
- be deleted or retained according to an explicit retention policy.

The source manifest and normalized text must remain sufficient to rebuild the index. Deleting the index must not delete the audit record.

Hosted embeddings are not “zero cost”; all embedding tokens and charges must be measured. A local embedding model may be configured to avoid hosted-model charges.

### FR-07 — Validated fork–join

In parallel mode, the Scout and Library shall start from the same immutable normalized request. The join shall not release the Critic until both required branch outputs pass schema, budget, and minimum-coverage checks.

Completion order must not change merged state. Results shall be merged by stable task and record identifiers.

### FR-08 — Critic worker and RAG loop

For each candidate, the Critic shall issue rubric-specific retrieval queries rather than one generic query. At minimum it shall retrieve evidence for:

- prior work and differentiation;
- feasibility and required resources;
- available data, tools, and evaluation methods;
- technical depth; and
- known limitations or risks.

Only the configured top-k chunks within the context budget shall be passed to the model. Each scored claim must cite the relevant `source_id` and chunk ID. The Critic must distinguish supporting, contradicting, and missing evidence and may revise or narrow a candidate, but the original candidate must remain in the audit trail.

### FR-09 — Scoring and gates

Scoring criteria and weights shall be configuration-driven and total 100. At minimum the rubric shall cover problem value, evidence quality, novelty/differentiation, feasibility, data/tool availability, technical depth, evaluation clarity, user-constraint fit, and delivery risk.

Hard gates shall override weighted scores. Recommended gates include:

- violates a user exclusion or mandatory constraint;
- lacks a plausible evaluation method;
- requires unavailable or prohibited data/resources;
- lacks enough evidence for a material feasibility claim; or
- cannot be scoped to the stated delivery window.

The model may propose evidence-backed criterion scores and rationales. Deterministic code shall validate ranges, calculate weighted totals, apply gates, and resolve documented tie-breaks.

### FR-10 — Final selection

The coordinator shall select the requested number of finalists from gate-passing candidates in deterministic score order. The default is exactly three. If fewer than three pass, the system shall return the valid candidates plus a coverage failure; it must not lower gates silently.

### FR-11 — Checkpoint and resume

The system shall write atomic, checksummed checkpoints after request normalization, both forked tasks, the join, Critic evaluation, and finalization. Resume shall rerun only missing or invalid work. A resumed run must produce the same merged state and ranking as an uninterrupted run given identical inputs and provider snapshots.

### FR-12 — Caching

Provider responses, normalized records, embeddings where permitted, and model results shall be cacheable by input and version hashes. Evaluation mode must be able to use frozen cached inputs so Approach A and B see identical evidence and repeated tests do not incur unnecessary external calls.

### FR-13 — Observability and usage accounting

Every task shall record task ID, role, attempt, provider, model, query/tool calls, source counts, start/end times, status, errors, prompt tokens, completion tokens, embedding tokens, estimated cost, and cache hits. Run-level totals must reconcile with task totals.

### FR-14 — Failure handling

Timeouts, rate limits, malformed results, insufficient sources, index failures, and model-output validation failures shall have explicit typed outcomes. A branch may retry once when configured. Required-branch failure stops the join unless the configuration defines and reports an evidence-coverage fallback. No sequential or single-agent fallback may occur silently.

### FR-15 — Search configuration model

Search behavior shall use one validated `SearchConfiguration` contract shared by the Streamlit UI, API, CLI, coordinator, and evaluation runner. It shall support:

- domain and optional subdomain;
- configuration mode and preset;
- included, excluded, and required source types;
- enabled providers, restricted to the operator-approved registry;
- permitted content types;
- date range or recency preference and language;
- evidence-tier requirements;
- per-source and total-result limits;
- metadata, abstract, snippet, README, and licensed full-text policy;
- timeout, request, byte, token, and cost limits;
- fallback behavior; and
- free-text search instructions.

Every run shall store the user-supplied configuration, deduced fields, applied defaults, final resolved configuration, configuration version, and checksum.

### FR-16 — Preavailable configuration catalog

The UI shall load available domains, source types, content types, presets, and providers from configuration rather than hard-code them in Streamlit components. The initial catalog shall include:

- common domains such as computer science, AI engineering, mathematics, robotics, engineering, life sciences, medicine, and social science;
- source types including scholarly article, preprint, official dataset, official documentation, technical report, code repository, community signal, and web article;
- content types including metadata, abstract, page snippet, dataset description, README, release notes, issue excerpt, and licensed full text; and
- `balanced`, `academic`, and `build-oriented` presets.

Operators may add catalog entries through configuration. Adding a new provider still requires an installed adapter. A user-defined phrase shall never create or activate an unapproved provider automatically.

### FR-17 — Simple configuration mode

Simple mode shall be the default and shall expose only the decisions most users understand:

1. domain, with an `Other` free-text option;
2. interests or subdomain;
3. search preset;
4. optional source-type choices;
5. recency preference;
6. evaluation-priority preset; and
7. optional natural-language instructions.

All other fields shall receive visible, documented defaults. Before starting, the UI shall show a short summary such as “balanced search; scholarly sources, datasets, and code; metadata and abstracts; public-access content; configured budget limits.”

### FR-18 — Advanced configuration mode

Advanced mode shall edit the same underlying `SearchConfiguration` contract and additionally expose:

- exact provider selection from enabled adapters;
- required and excluded source types;
- allowed content types and full-text policy;
- evidence tiers;
- publication date range and language;
- maximum records per source type and total records;
- query, page, byte, token, time, and cost budgets;
- deduplication and retrieval top-k settings;
- exact evaluation-criterion weights; and
- explicit fallback behavior when a provider or evidence class is unavailable.

Advanced mode shall not bypass operator security rules, unavailable credentials, licensing restrictions, or global budget caps. Switching between modes shall preserve compatible values; returning to simple mode shall summarize advanced values rather than silently discard them.

### FR-19 — Natural-language configuration deduction

Users may describe search preferences in their own words, for example: “Use recent peer-reviewed AI papers and GitHub projects, only abstracts, and no blogs.” The system shall convert this text into proposed structured fields, while preserving the original text.

Each deduced field shall record whether it came from an explicit control, natural-language deduction, preset, or system default. Unsupported or ambiguous instructions shall be highlighted for confirmation. The system shall not invent credentials, providers, source availability, or permissions. User corrections shall override deductions and be stored in the run record.

Configuration precedence, from highest to lowest, shall be:

1. operator security, licensing, and global budget policy;
2. explicit advanced-mode values;
3. explicit simple-mode values;
4. confirmed natural-language deductions;
5. preset values; and
6. system defaults.

Contradictions, such as requiring and excluding the same source type, must block the run with an actionable validation error.

### FR-20 — Streamlit configuration experience

The Streamlit application shall provide a visible Simple/Advanced mode selector, prompt input, editable resolved fields, search-configuration summary, validation feedback, and a deliberate start action. Network research shall not begin while the user is still editing or while required fields are unresolved.

During a run, the UI shall display the resolved configuration, selected source adapters, progress, coverage warnings, and budget usage. After completion, the user shall be able to inspect which configuration and source types produced each cited result.

### FR-21 — User-configurable evaluation weights

The user shall be able to control the relative importance of the evaluation criteria used to rank candidates. The initial criteria shall include problem value, evidence quality, novelty or differentiation, feasibility, data and tool availability, technical depth, evaluation clarity, user-constraint fit, and delivery risk.

Simple mode shall offer understandable rubric presets, including at least:

- `balanced` — no criterion family dominates;
- `feasibility-first` — favors achievable scope, available data and tools, and delivery risk;
- `innovation-first` — favors novelty and technical depth; and
- `evidence-first` — favors evidence quality and evaluation clarity.

Advanced mode shall allow the user to enter an explicit percentage weight for every criterion. Weights shall be non-negative and total exactly 100 before a run can start. The UI may offer an explicit “normalize to 100” action, but it shall show the adjusted values and require confirmation rather than change weights silently.

Natural-language instructions such as “feasibility matters twice as much as novelty” or “prioritize evidence and practical delivery” may be converted into proposed weights. The original instruction, proposed weights, value origins, user corrections, resolved weights, rubric version, and checksum shall be stored in the run record.

Weights affect weighted scoring and deterministic ranking. They shall not disable hard gates, permit prohibited projects, weaken citation requirements, or change score ranges. If a user assigns zero weight to a criterion, that criterion shall still be evaluated and recorded for audit purposes. Identical candidate scores and resolved weights must produce identical totals and ranking.

## 8. Data surface

The initial data surface is a configurable source registry, not a promise to support every provider on day one.

| Source class | Examples / candidate adapters | Data used | Purpose | Key controls |
|---|---|---|---|---|
| Broad scholarly index | OpenAlex, Crossref, CORE | metadata, abstracts where available, citations/concepts | domain landscape and source discovery | licensing, abstract availability, rate limits |
| Preprint repository | arXiv and domain categories | title, abstract, authors, dates, category | CS, math, physics, robotics, related engineering | category routing, version/date capture |
| Biomedical literature | PubMed or Europe PMC | metadata, abstracts, publication types | medicine, health, biology | evidence-type labels; no medical advice claims |
| Engineering library | IEEE Xplore where credentials permit | metadata and abstracts | electrical, mechanical, and robotics evidence | optional credentialed adapter; never assumed available |
| Project/code ecosystem | GitHub or equivalent public repository search | repository metadata, README snippets, releases, topics | available tools, implementations, maintenance signals | no code execution; immutable receipt where possible |
| Web/community signals | configured search provider and allowlisted pages | short snippets and page excerpts | problems, unmet needs, user language | lower evidence tier; prompt-injection defenses |
| Local frozen fixtures | checked-in JSON/Markdown | synthetic records | deterministic tests and demos | visibly labeled synthetic; excluded from empirical claims |

### 8.1 Evidence tiers

The system shall label evidence rather than treating every source equally:

1. **Primary/authoritative:** official datasets, standards, documentation, registries, or original studies.
2. **Scholarly/technical:** papers, preprints, reputable technical reports, and maintained repositories.
3. **Opportunity signal:** issue trackers, forums, community discussions, project lists, and blogs.
4. **Synthetic fixture:** test-only data with no real-world evidentiary weight.

Novelty and feasibility claims should use primary or scholarly evidence when available. Opportunity signals can motivate a problem but cannot by themselves prove scientific novelty or technical feasibility.

### 8.2 Source-selection policy

Source selection shall optimize for relevance, recency appropriate to the field, evidence-tier diversity, and coverage—not an unsupported “most cited” claim. The Library must record its query plan and why each source class was used. A default target of 30–50 normalized abstracts/records is a tunable budget, not a correctness requirement.

### 8.3 Configuration layers

Configuration has three distinct owners:

| Layer | Owner | Examples |
|---|---|---|
| Registry | operator | installed adapters, credentials, allowed providers, supported source/content types |
| Defaults and presets | operator | balanced preset, corpus limits, recency, content-access policy |
| Per-run preferences | user | domain, required/excluded sources, content types, natural-language instructions |

The resolved search plan is the intersection of these layers. User preferences may narrow or select enabled capabilities but may not grant access that the registry forbids. If the requested intersection is empty, the system shall explain which requirement could not be satisfied.

### 8.4 Source type versus content type

The system shall keep these concepts separate:

- **Source type** describes what the item is, such as a scholarly article, dataset, repository, or community post.
- **Content type** describes what may be captured from it, such as metadata, abstract, snippet, README, issue excerpt, or full text.
- **Provider** describes where it came from, such as OpenAlex, arXiv, PubMed, or GitHub.

A provider may emit multiple source types and content types. Provider names shall not be used as substitutes for either classification.

## 9. Data contracts

The implementation shall define validated schemas for at least:

- `CapstoneRequest`;
- `SourceConfiguration`, `SearchConfiguration`, and `ResolvedSearchConfiguration`;
- `EvaluationConfiguration` and `ResolvedEvaluationConfiguration`;
- `TaskPlan` and `TaskResult`;
- `CandidateIdea`;
- `SourceRecord` and `SourceChunk`;
- `RetrievalResult`;
- `CriterionScore` and `CandidateEvaluation`;
- `UsageRecord`;
- `FinalProposal`; and
- `RunManifest`.

All schemas require a version. Unknown fields shall either be rejected or retained according to a documented compatibility policy. Model outputs must be schema-validated before they affect run state.

## 10. Non-functional requirements

### NFR-01 — Determinism

Given frozen inputs, configuration, model outputs, and source snapshots, task completion order shall not change the normalized corpus, scores, gates, or ranking.

### NFR-02 — Bounded operation

The system shall enforce global and per-task limits for concurrency, retries, search calls, fetched pages, bytes, corpus records, chunks, retrieval top-k, prompt tokens, output tokens, elapsed time, and estimated cost.

### NFR-03 — Security and trust

Retrieved text is untrusted data. The system shall never execute it or allow it to override coordinator instructions. Credentials remain inside provider adapters and must not appear in prompts, checkpoints, logs, or generated documents. External content must be size-limited and sanitized before model use.

### NFR-04 — Privacy

The MVP shall use public or explicitly supplied sources. It shall not collect private student data beyond the request, and shall define retention for requests, caches, manifests, and temporary indexes.

### NFR-05 — Provenance and reproducibility

Every source-derived material claim must be traceable to a source receipt. Each run shall record configuration, schema versions, code version, provider/model versions, timestamps, query plan, and content hashes sufficient to explain or reproduce the run within provider constraints.

### NFR-06 — Portability

Core orchestration, validation, scoring, and artifact generation shall not depend on one LLM or vector database vendor. Provider-specific logic belongs behind adapters.

### NFR-07 — Performance

Parallel mode shall not exceed the configured concurrency limit. Latency targets must be established from the sequential baseline; the transcript's suggested percentage reduction is not an accepted measurement.

### NFR-08 — Cost transparency

The application shall display the estimated cost of a run and its stage-level breakdown. It shall support an offline fixture mode and frozen-cache evaluation mode that make no paid requests.

### NFR-09 — Configuration clarity

A user shall be able to explain, from the pre-run summary, which domains, source types, content types, providers, evaluation weights, and limits will be used. Defaults and deduced values must be visibly distinguishable from explicit choices. Simple and advanced modes must resolve to the same result when they express equivalent settings.

## 11. Evaluation requirements

### 11.1 Frozen evaluation set

Create a versioned set of at least 20 requests spanning at least three domain families, including difficult constraint combinations. Separate any prompt-development examples from the held-out evaluation set. Store the request, source snapshot or cache, human annotations, reviewer, date, and system output. Synthetic cases may test behavior but must be reported separately from real-source cases.

### 11.2 A/B protocol

Run sequential Approach A and parallel Approach B on identical normalized requests, frozen provider responses, models, prompts, budgets, retrieval configuration, and rubric. Repeat enough times to measure latency variance. Do not compare a warm cached parallel run with a cold uncached sequential run.

### 11.3 Metrics

| Dimension | Required measurements |
|---|---|
| System | end-to-end and per-stage p50/p95 latency, success/failure rate, retries, cache hit rate |
| Retrieval | context precision@k, context recall on annotated claims where feasible, source diversity, empty-retrieval rate |
| Grounding | citation correctness, citation completeness, faithfulness/unsupported-claim rate |
| Output quality | constraint adherence, candidate diversity, feasibility, usefulness, evaluation clarity |
| Configuration | deduction accuracy, explicit-value preservation, rubric-weight resolution, simple/advanced equivalence, invalid-combination rejection |
| Determinism | ranking agreement across completion-order permutations and frozen reruns |
| Cost | prompt, completion, and embedding tokens; estimated cost per successful run and stage |
| Safety | prompt-injection resistance, credential leakage, prohibited execution attempts, correct abstention |

### 11.4 Qualitative review and LLM-as-a-judge

Use a fixed 1–5 rubric for usefulness, specificity, evidence sufficiency, feasibility, and actionability. Human reviewers shall assess a representative subset with randomized A/B labels. An LLM judge may supplement but not replace human review; its rubric, model, prompt, and agreement with humans must be reported.

### 11.5 Initial target thresholds

These are design targets, not measured claims:

- 100% schema-valid final outputs on successful runs;
- 100% identical rankings across randomized fork completion order with frozen inputs;
- at least 0.90 citation correctness on the reviewed set;
- zero accepted material claims that cite no source record;
- at least 0.90 user-constraint adherence on reviewed outputs;
- no silent gate lowering or silent fallback;
- parallel median pre-Critic latency lower than the sequential baseline, with no material quality regression; and
- run cost at or below the configured cap.

### 11.6 Failure analysis

For every false citation, unsupported claim, missed constraint, retrieval miss, invalid output, and orchestration failure, record the case, expected behavior, observed behavior, severity, evidence, root-cause hypothesis, pivot, and retest result. Negative or inconclusive results must remain in the project history.

## 12. Acceptance criteria

The MVP is accepted when all of the following are demonstrated:

1. A user can submit a valid request and receive three proposals, or an explicit evidence/coverage failure when three cannot pass.
2. The sequential and parallel modes execute the same logical tasks and produce the same final ranking on frozen inputs.
3. In parallel mode, Scout and Library overlap in time and the Critic starts only after both valid results exist.
4. The Library's query plan is derived independently of the Scout's output.
5. At least three domain families complete using configured source routing.
6. Every final material claim and criterion rationale is linked to stored source/chunk receipts.
7. Workers cannot mutate coordinator-owned run state or select finalists.
8. Budget exhaustion, one branch failure, malformed model output, empty retrieval, and resume after interruption are covered by tests.
9. Temporary index retention behaves as configured and the run remains auditable after index deletion.
10. Token and estimated-cost totals reconcile across tasks and the run.
11. The A/B evaluation reports both quality and latency results without presenting targets or synthetic fixtures as measured real-world performance.
12. README documentation identifies attempted approaches, failures, pivots, known limitations, and exact reproduction commands.
13. Simple mode produces a valid resolved configuration using documented defaults and exposes a readable pre-run summary.
14. Advanced mode permits provider, source-type, content-type, recency, evidence-tier, budget, and fallback configuration within operator limits.
15. Natural-language instructions are converted into editable structured values, with ambiguous and unsupported instructions surfaced before research starts.
16. Equivalent simple and advanced inputs produce the same resolved configuration checksum and source plan.
17. Conflicting source rules, unavailable required providers, and attempts to exceed policy limits fail with actionable errors and do not start external calls.
18. Every completed run records the original instructions, value origins, resolved configuration, selected adapters, and applied limits.
19. Simple mode applies the selected evaluation-priority preset and shows the resolved criterion weights before the run.
20. Advanced mode accepts non-negative criterion weights totaling 100, rejects invalid totals, and makes normalization an explicit confirmed action.
21. Changing only evaluation weights leaves candidate evidence unchanged, recalculates totals deterministically, and never bypasses a hard gate.

## 13. Recommended MVP delivery order

1. Define request, search-configuration, evaluation-configuration, source, scoring, receipt, and run-manifest schemas.
2. Implement the configuration catalog, search and rubric presets, resolution rules, and frozen-fixture adapter.
3. Implement the Streamlit request flow with Simple mode, natural-language deduction preview, and resolved summary.
4. Implement one real domain adapter and the sequential baseline end to end.
5. Add Advanced mode, configuration validation, and operator-limit enforcement.
6. Add the temporary retrieval index and citation-preserving Critic queries.
7. Add the bounded parallel coordinator using native asynchronous tasks.
8. Add two more domain routes and explicit insufficient-evidence behavior.
9. Freeze the evaluation set; run configuration, A/B, retrieval, and UI checks.
10. Perform failure analysis, document pivots, and prepare the three-minute demo.

An orchestration framework may be introduced only if native asynchronous execution cannot meet a documented requirement. Framework choice is an implementation decision, not a product requirement.

## 14. Open design decisions

The design review must resolve these items before implementation is considered complete:

- default rubric weights, preset weights, permitted user ranges, and hard-gate thresholds;
- initial three domain families and their enabled source adapters;
- hosted versus local embedding model;
- vector-only versus hybrid lexical/vector retrieval;
- default corpus size, chunking, top-k, and context-token limits;
- worker failure and minimum-coverage policy;
- exact initial preset definitions and which advanced controls are shown in the MVP;
- confidence and confirmation thresholds for natural-language configuration deduction;
- cache and temporary-index retention periods;
- per-run cost and wall-clock caps; and
- the human annotation protocol for retrieval relevance and proposal quality.
