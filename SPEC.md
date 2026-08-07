# SPEC — Phase 7: Multi-source job discovery

## Goal

Discovery is no longer limited to Adzuna. Users can enable multiple **free**
official job APIs — RemoteOK, Arbeitnow — alongside Adzuna, and Cinch fans out
to all of them in one cycle. Immediate user-visible impact: `/discover` returns
many more (and often more relevant) postings, even when Adzuna's free tier
returns 0 for a query.

## Non-goals

- No scraping. All new sources are documented public JSON APIs.
- No LinkedIn/Indeed automation of any kind (see [SECURITY.md](SECURITY.md) — the
  project's non-negotiable rule).
- No ATS-aware submission decisions yet — that's the follow-up Phase 7b.
- No JSearch/RapidAPI adapter yet — deferred to Phase 7b (needs signup).

## Design

- **`RawJob.source: JobSourceName | None`** — each adapter stamps its own
  identity so the multi-source pipeline can preserve provenance. Optional for
  backward compatibility; discovery falls back to the calling
  `JobSource.source_name` when unset.
- **New adapters** — `RemoteOKJobSource`, `ArbeitnowJobSource`. Both use free
  public JSON endpoints with no auth. Each sets a Cinch `User-Agent`, strips
  HTML from descriptions (rough regex + `html.unescape`), and filters
  client-side against `JobQuery.what` since the free feeds don't accept
  server-side keyword params.
- **`CompositeJobSource`** — fans out to N adapters via `asyncio.gather`.
  Per-source failures are caught and logged (`composite_source_failed`) so one
  dead API can't kill the whole cycle. Deduplication is deliberately left to
  `JobRepository`'s existing `(source, external_id)` unique constraint — the
  same posting from two sources is stored twice (once per source), which is
  the correct behaviour (they're separate postings with separate apply URLs).
- **`JOB_SOURCES`** env var — comma-separated list. Default `"adzuna"`
  preserves prior behaviour. Common production configs: `"adzuna,remoteok,arbeitnow"`,
  or `"remoteok,arbeitnow"` for a fully-free setup with no Adzuna signup.
- **Fail-soft factory** — sources with missing credentials are logged and
  skipped rather than raising. If only one source survives, it's returned
  directly (no composite wrapper). Only when zero sources survive does the
  factory raise `JobSourceError`.

## Interfaces & files

**New:**
- `src/cinch/providers/jobs/remoteok.py` — `RemoteOKJobSource` + `_strip_html`.
- `src/cinch/providers/jobs/arbeitnow.py` — `ArbeitnowJobSource`.
- `src/cinch/providers/jobs/composite.py` — `CompositeJobSource` (concurrent
  fan-out, per-source error isolation).
- `tests/test_remoteok.py` — 4 tests (parse + filter + source-stamp + HTTP error + strip helper).
- `tests/test_arbeitnow.py` — 3 tests (parse + filter + source-stamp + malformed-JSON + HTTP error).
- `tests/test_job_source_composite.py` — 8 tests (merge, per-source isolation,
  factory: single vs composite, missing creds skipped, unknown names skipped,
  no-source-survives raises).

**Modified:**
- `src/cinch/domain/enums.py` — added `JobSourceName.REMOTEOK`, `ARBEITNOW`.
- `src/cinch/providers/jobs/base.py` — `RawJob.source` optional field.
- `src/cinch/providers/jobs/adzuna.py` — stamps `source=ADZUNA`.
- `src/cinch/providers/jobs/__init__.py` — `get_job_source` now iterates
  `settings.job_sources`, builds each adapter (fail-soft), returns single
  source or composite as appropriate.
- `src/cinch/core/config.py` — `job_sources: str = "adzuna"` setting.
- `src/cinch/services/discovery.py` — persists jobs under `raw.source or
  self._job_source.source_name` (backward compatible).
- `tests/test_adzuna.py` — asserts `RawJob.source` is stamped now.
- Docs: SPEC + README + `.env.example`.

## Safety properties (asserted by tests)

1. Every adapter's `RawJob` carries its own `source` value (Adzuna, RemoteOK, Arbeitnow).
2. Client-side keyword filter matches title OR any tag — not fabricated relevance.
3. HTML content in descriptions is stripped before storage (LLM prompts stay clean).
4. `CompositeJobSource` never dies from a single upstream failure; peers still deliver.
5. Factory skips sources with missing creds (partial config still works).
6. Factory raises loudly if zero sources survive (never silently return empty).

## Verification

- `uv run ruff check .` · `ruff format --check .` · `uv run mypy` ·
  `uv run pytest` — all green, coverage ≥ 80%.
- Manual smoke (post-deploy): set `JOB_SOURCES=adzuna,remoteok,arbeitnow` in
  Render → save → wait for redeploy → `/discover` in Telegram → you should see
  jobs from multiple sources (visible in the Job's `source` column in the DB
  and in future dashboard views).

## Out of scope (future work — Phase 7b)

- JSearch (RapidAPI free tier) adapter.
- ATS detection from apply URL (Greenhouse/Lever/Workable/Ashby) so Phase 6
  auto-submits only on ATS-eligible postings and hands off LinkedIn/Indeed.
- Per-source rate-limit budgets (currently we rely on discovery-interval politeness).
- Result-level dedup across sources (same job from Adzuna + Arbeitnow — currently
  stored twice under different sources, which is intentional but reviewable).
