# DeepMind CodeContests integration plan

## Goal

Add CodeContests as a first-class practice collection in the online judge while preserving the current LeetCode catalog and making contest-style stdin/stdout problems work correctly.

## What we have

- The attached `dm-code_contests.zip` is about 3.02 GB and contains 128 training Riegeli shards, one validation file, and one test file. It is not JSONL and cannot be passed to the existing importer as-is.
- CodeContests records are `ContestProblem` protocol buffers. They include a name and statement; public, private, and generated input/output tests; correct and incorrect solutions; source, difficulty, Codeforces rating and tags; time and memory limits; and sometimes file-based I/O.
- This workspace already has a SQLAlchemy problem catalog and an importer for JSONL. Its current problem/editor flow is designed around starter code. The judge runs Python locally, and the canonical API can include every test case and its input/output in execution results.
- The existing catalog has about 4,100 problems. CodeContests would be a second, substantially different source rather than a replacement for that catalog.

## Recommended product decision

Expose CodeContests as a clearly labeled **Contest Practice** collection, with its source and contest metadata visible on each problem. Keep it distinct in filtering and browsing from the existing LeetCode problems.

Make training and validation records eligible for practice after quality checks. Keep the test split out of normal browsing and submissions so it remains available for controlled evaluation. Preserve the original split on every record so this policy can be changed deliberately later.

Treat the dataset's difficulty enum as source-specific metadata. Prefer Codeforces rating when available, show the original rating/source, and avoid silently converting non-comparable contest grades into the platform's Easy/Medium/Hard scale. Keep unknown difficulty as unknown.

## Data and identity rules

| CodeContests field | Platform treatment |
| --- | --- |
| `name`, `description` | Title and statement; retain original text and provenance. |
| `source`, `cf_contest_id`, `cf_index` | Source metadata and stable external identity. |
| Split and shard/record position | Store for filtering, repeatable imports, audit, and test-split exclusion. |
| `cf_tags` | Searchable tags, namespaced or kept alongside the source tags. |
| `cf_rating`, `cf_points`, difficulty enum | Store without lossy conversion; use rating as the primary contest difficulty signal. |
| `public_tests` | Visible examples in the problem workspace. |
| `private_tests`, `generated_tests` | Hidden judge cases; never serialize their contents in public API responses. |
| `solutions`, `incorrect_solutions` | Retain with provenance and language metadata for internal evaluation/enrichment only. Never send reference or incorrect code to the learner client. |
| `time_limit`, `memory_limit_bytes` | Convert units into the platform's limit fields and apply enforced limits in the execution service. |
| `input_file`, `output_file` | Mark as unsupported until a sandbox can safely provide the required files; do not silently run such problems as stdin/stdout. |

Use a source-qualified stable key, for example `code_contests:<source>:<contest_id>:<index>` (with a deterministic fallback based on source and record identity). Do not use a title or a bare contest ID as the unique key. Generate stable slugs from that key so repeated imports update the same row and do not collide with LeetCode slugs.

## Implementation phases

### 1. Inspect, decode, and profile the archive

1. Confirm the expected archive entries, split counts, shard numbering, checksums, and available disk space before extraction or import.
2. Use the official schema and reader conventions to decode Riegeli records. Build a streaming converter/import path rather than loading the entire archive into memory or maintaining a full intermediate JSONL copy.
3. Profile each split for record counts, missing statements, test counts, source distribution, language distribution, time/memory limits, file-based I/O, duplicate identities, and malformed records.
4. Produce a machine-readable import manifest and a human-readable quality report before writing to the live catalog.

**Exit condition:** every input record is accounted for as imported, intentionally excluded, or failed with a reason; split and source counts reconcile with the archive.

### 2. Extend the model for source and contest metadata

1. Add a dataset/source identifier and source-qualified external ID, split, original source, Codeforces contest/index/rating/points, and original difficulty value.
2. Preserve the raw record or a durable source reference plus hash. Avoid copying all solution/test payloads into one large JSON text field if normalized tables and source metadata can retain what the app needs.
3. Store tests with visibility and origin (`public`, `private`, `generated`) instead of representing all test semantics with a single sample flag. Preserve stable test order.
4. Store input/output execution mode and file-I/O requirements. Add database migrations and indexes for dataset, split, source, rating, and contest browse filters.
5. Keep existing LeetCode defaults and API behavior intact; make source-specific fields optional for existing rows.

**Exit condition:** old catalog data loads unchanged, and CodeContests records can be represented without dropping source identity, split, test visibility, limits, or execution mode.

### 3. Implement an idempotent Riegeli importer

1. Add a dedicated importer that reads shards incrementally and writes bounded database batches with transactional rollback and per-record error isolation.
2. Support dry-run/profile mode, selected split/shard import, resume/retry, upsert, and a structured audit report.
3. Deduplicate by source-qualified identity, not title. Ensure a second import has no duplicate records and does not erase submissions or user progress.
4. Keep raw-source hashes and importer/schema version in the audit so future re-imports can be traced.
5. Stage into a separate database or staging namespace first. Do not import the test split into the live practice catalog by default.

**Exit condition:** repeat import is idempotent; failure/restart does not leave partially replaced test or metadata rows; audit totals reconcile.

### 4. Support contest-style stdin/stdout problems in the judge

1. Add an explicit execution mode for complete programs that read stdin and write stdout. Do not manufacture function templates for records that have none.
2. Update readiness rules: a problem is ready when its statement, supported execution mode, at least one usable public case, and a compatible runtime are available; a starter template is optional in contest mode.
3. Render public sample input/output in the workspace and initialize the editor with a short stdin/stdout scaffold only if useful. Preserve the user's code workflow and existing function-style problems.
4. Compare outputs using a documented policy that tolerates standard whitespace differences while preserving meaningful token differences. Confirm expected newline behavior.
5. Enforce time and memory limits in an OS/container-level sandbox before enabling public submissions. The current development executor is not a security boundary for untrusted code.
6. Return only verdict, counts, and safe aggregate runtime for hidden cases. Never return hidden inputs, expected outputs, reference solutions, or raw hidden-case errors. Add an API-level privacy check before exposing CodeContests submissions.
7. Initially enable only languages supported by the platform's hardened runtime. The dataset's stored solutions in Python 2, Python 3, C++, and Java do not mean those runtimes are already available in this platform.

**Exit condition:** a complete stdin/stdout solution can pass public cases and be judged against hidden cases, while the API/UI reveals only public cases and safe hidden-case results.

### 5. Add catalog discovery and source-aware UI

1. Add collection/source filters and labels (for example, LeetCode and Contest Practice).
2. Add filters for contest source, topic, Codeforces rating band, and optional contest ID/index.
3. Show source attribution and Codeforces rating where available. Do not display popularity or acceptance percentages unless the platform has measured them.
4. Ensure dashboard counts, challenge-of-the-day, study-plan recommendations, search, pagination, and progress remain correct when the catalog contains multiple sources.
5. Make hidden tests and solution metadata inaccessible from both API DTOs and client bundles.

**Exit condition:** users can find and identify these problems without confusing their ratings or source-specific metadata with the existing catalog.

### 6. Validate, pilot, then roll out

1. Validate field mapping, identity collisions, source counts, split policy, tags, ratings, limits, test visibility, and import idempotency.
2. Run a representative private pilot across sources, ratings, languages, small/large tests, and edge-case output formatting.
3. Manually review a sample of statements and expected outputs against the original records.
4. Verify migration rollback, backup/restore, importer restart, and query performance at the expected catalog size.
5. Enable the validated train/validation collection behind a feature flag; monitor import failures, judge verdict distribution, runtime/memory failures, and user-reported statement/test issues.
6. Keep the test split excluded unless a separate evaluation workflow is explicitly designed.

## Acceptance criteria

- Existing LeetCode records, slugs, submissions, progress, filters, and execution behavior are preserved.
- Every admitted CodeContests row has stable source-qualified identity, split provenance, source attribution, and an auditable raw-source hash.
- Dataset and split totals reconcile with the import manifest; failed or excluded records have explicit reasons.
- Public tests are visible; private/generated tests, solutions, and incorrect solutions remain server-side.
- Contest-mode programs can run with stdin/stdout and enforced resource limits in a hardened sandbox.
- File-I/O cases and unsupported languages are clearly excluded or explicitly marked unavailable, never presented as solvable when they are not.
- Re-import is idempotent, does not duplicate rows, and preserves user data.
- Collection filters, ratings, topic tags, dashboard counts, and pagination work across both datasets.

## Main risks and mitigations

- **Archive size and parsing cost:** use streaming shard reads, bounded batches, staging, and progress manifests.
- **Public test leakage:** distinct visibility metadata and response allowlists; hide all hidden-case payloads at the API boundary.
- **Unsafe execution:** current Python subprocess executor is development-only. Gate public judge submissions on container-level isolation and enforced limits.
- **Difficulty mismatch:** preserve original difficulty and rating; do not map contest grades to LeetCode levels without a calibrated policy.
- **Source licensing/provenance:** retain attribution and original source metadata and review third-party source terms before public redistribution.
- **Duplicate or misleading problems:** source-qualified IDs and slugs; retain split and source; add quality checks and a report before release.
- **Test split contamination:** exclude it from normal browsing and keep split provenance enforceable in queries.

## Suggested delivery order

1. Schema/migration and import profiling.
2. Streaming Riegeli decoder and staging importer.
3. Source-aware API and private-test-safe result DTOs.
4. Contest-mode stdin/stdout workspace and sandbox integration.
5. Catalog filters and attribution UI.
6. Pilot, audit, and feature-flagged rollout.

## Source references

- Attached archive: `C:\Users\jyoti\Downloads\dm-code_contests.zip`; its embedded README identifies the Riegeli files and directs readers to the official schema.
- [Official CodeContests repository and dataset documentation](https://github.com/google-deepmind/code_contests)
- [Official `ContestProblem` Protocol Buffer schema](https://github.com/google-deepmind/code_contests/blob/main/contest_problem.proto)
- [Official license and third-party data notes](https://github.com/google-deepmind/code_contests#license)

The official repository states that data files are Riegeli-encoded `ContestProblem` protocol buffers, describes the train/validation/test splits, documents the public/private/generated test distinction and execution limits, and identifies CC BY 4.0 for non-code materials while calling out separate third-party terms. Attribution and terms should be reviewed for the intended distribution and use.
