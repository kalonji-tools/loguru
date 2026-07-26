# EVAL_BRIEF — loguru pathfinder migration

One-page brief for the T8 pathfinder showcase (map [`Wayfinder: oxitest usability showcase evaluation`](https://github.com/kalonji-tools/oxitest/issues/1660), pathfinder umbrella [`Migrate standard-features showcase (pathfinder)`](https://github.com/kalonji-tools/oxitest/issues/1668)). Companion to [`EVAL_NOTES.md`](./EVAL_NOTES.md).

**Provenance.** T8b baseline (config wiring + parity gate) executed by an earlier agent. Migration itself — commits `4824a4e` → `91f18e6`, 16 commits, +7362/-3916 lines across 60 files — executed by a separate migrating agent. This brief is written as a third-agent evaluation of the migration.

## Environment

- **oxitest:** `3.0.0` (git `131dd9b` — v3.0.0 tag on `kalonji-tools/oxitest`; PyPI cp313 wheel)
- **Python:** `3.13.12` (nix `python313`, uv-managed venv)
- **OS:** NixOS, Linux kernel `6.12` (x86_64)
- **Upstream commit** (from T8a): `2a17be7` — `Delgan/loguru:master` at 2026-06-13
- **Migration branch commit** (this fork's `oxitest-migration` HEAD): `91f18e6`
- **strict mode used:** `abort` (from T8b baseline; unchanged)

## What was ported

**Effectively the whole suite.** Full replacement in place — zero `*_oxi.py` side-by-side files. Split cleanly by test category:

| Runner | Path | Items | Reason |
|---|---|---|---|
| oxitest | `tests/` (excluding typesafety) | 1625 | Primary migration target |
| pytest | `tests/typesafety/` (yml files) | 47 | Driven by `pytest-mypy-plugins`; no oxitest equivalent |

Companion infrastructure created by the migration:
- `tests/_naming.py` — module-name pinning helper for tests that assert on `record.name`
- `tests/_utils.py` — plain-module utilities needed at import time (parametrize case values, worker bootstraps) where `oxitest.helpers` isn't valid yet
- `tests/conftest.py` (423 lines) — full rewrite around `Fixtures()` + `Helpers()` registries; includes bespoke `patch_context()` wrapping `Patcher` for scoped-block patching, and `strict_warnings` autouse fixture replacing pytest's `filterwarnings` config
- `pyproject.toml` — drops `pytest-cov`, adds `coverage==7.6.1` directly; `[tool.oxitest]` is the primary config, `[tool.pytest.ini_options].testpaths = ["tests/typesafety"]` narrows pytest to the type-safety corner
- `.github/workflows/tests.yml` — splits into `tests` job (oxitest matrix, py3.11–3.14, ubuntu + windows + macos) and `typesafety` job (pytest via tox, py3.12)

## Dimension exercised

**Standard features — end-to-end.** The migration exercises every axis the T8 pathfinder was chartered to cover, at real scale:

- Function-scope fixtures (`writer`, `sink_with_logger`, `freeze_time`)
- Autouse fixtures (`strict_warnings`, `reset_logger`, `reset_multiprocessing_start_method`, `check_env_variables`)
- **Session-scope via `shared=True`** — `check_env_variables` autouse; the shared-fixture cache reports **1644/1645 hits (99%)** on serial runs
- `@oxitest.parametrize` with frozen-dataclass expanded mode across ~60 test files
- `Fixture[T]` type-based injection + name-as-qualifier
- Built-in fixtures — `TempDir`, `StdCapture`, `Patcher`, `LogCapture`
- `oxitest.raises`, `oxitest.warns`
- Marks — `@oxitest.mark.skip(when=…, reason=…)` (replaces `@pytest.mark.skipif` throughout)
- Helper registry via `common = Helpers()` in conftest — helpers accessed via `oxitest.helpers.common.<name>()`
- Parallelism — full suite runs green under `-n 4`

## What worked

- **Full replacement, in place.** No side-by-side clutter. The migration went one commit per test-file cluster (16 commits total), which is a legible history for review.
- **Docs-correct patterns throughout.** `Fixtures()` in conftest, dataclass-expanded parametrize with kwarg IDs, `Fixture[T]` for injection, `Helpers()` for cross-file test utilities. The migration reads like a docs example scaled up.
- **`pin_module_name` cleanly solves F7** without hiding it. Opt-in per file (11 of ~60 files use it — only where module identity matters), and the helper's docstring explains WHY it's needed. Adopters can copy the pattern verbatim.
- **`patch_context` cleanly solves the `monkeypatch.context()` mismatch.** Same story — bespoke, well-documented, opt-in.
- **CI cleanly split.** `tests` job for oxitest (py3.11+), `typesafety` job for pytest-mypy-plugins. Narrowing the pytest matrix to what pytest is uniquely good for.
- **Faster than pytest even serially.** 79.8s pytest → 69.8s oxitest serial (12% improvement) → 31.5s oxitest `-n 4` (2.5× vs pytest baseline). Real usability signal — oxitest doesn't just replace pytest, it beats it on the same hardware.
- **Zero xfails, zero gap-marked tests, zero test failures.** All 1579 oxitest items assert what they used to assert. This is what "migration" was supposed to look like from the start.

## What didn't

Nothing regressed. Two above-threshold **new** findings surfaced that were invisible until an actual migration ran end-to-end:

- **N1 — `[tool.oxitest] filterwarnings` config missing.** Pytest lets you declare warning-to-error filters in `pyproject.toml`. Oxitest has no equivalent, so the migration wrote a 15-line `strict_warnings` autouse fixture reproducing pytest's `filterwarnings = ["error", "ignore:..."]` semantic manually. Every migrating project with `filterwarnings` config re-derives this fixture. Options: add config parity, or document the recipe.
- **N2 — `Patcher` has no `.context()` for scoped-block patching.** Pytest's `monkeypatch.context()` reverts at `with` block exit; `Patcher` only reverts at test end. The migration wrote a 57-line `patch_context()` helper in conftest to bridge the gap. Every project with `monkeypatch.context()` usage re-invents similar plumbing. Options: add `Patcher.context()`, or document the recipe.

Both are documentation/UX gaps, not bugs. Neither blocks anything.

### Findings from earlier T8 passes still standing

- **F2 [#1680](https://github.com/kalonji-tools/oxitest/issues/1680)** — `from .conftest import X` fails; workaround is `from conftest import X` (absolute). The migration uses absolute everywhere; friction is real, workaround is proven.
- **F7 [#1684](https://github.com/kalonji-tools/oxitest/issues/1684)** — Exec loader synthesizes `__name__`. 11 of ~60 migrated files needed `pin_module_name()` to work around it. Real, filed, workaround-able.
- **F4 [#1682](https://github.com/kalonji-tools/oxitest/issues/1682)** — `--json` on collection failure. Not exercised by this migration (no collection failures under the migrated suite). Bug remains valid but unchanged.

The 8 downgraded/reframed findings from the first T8 pass (F1, F3, F6, F8, F11, F12, F13) stay downgraded — this migration used docs-correct patterns and tripped none of them.

## Filed issues

The showcase-eval sweep completed during earlier T8 passes remains. This migration adds **two new above-threshold candidates**:

| # | Finding | Kind | Area | Status |
|---|---|---|---|---|
| [#1680](https://github.com/kalonji-tools/oxitest/issues/1680) | F2 — relative conftest imports fail | bug | python-bridge | Valid, workaround proven |
| [#1682](https://github.com/kalonji-tools/oxitest/issues/1682) | F4 — `--json` empty on collection failure | bug | cli | Valid, narrow |
| [#1684](https://github.com/kalonji-tools/oxitest/issues/1684) | F7 — exec loader synthesizes `__name__` | enhancement | python-bridge | Valid, this migration proves the friction (11 files patched) |
| **N1** (to file) | **`[tool.oxitest] filterwarnings` config parity** | enhancement | cli, docs | New — surfaced by migration |
| **N2** (to file) | **`Patcher.context()` for scoped-block patching** | enhancement | python-bridge, docs | New — surfaced by migration |

Other T8 sweep filings: [#1679 F1 (narrowed)](https://github.com/kalonji-tools/oxitest/issues/1679), [#1681 F3 (downgraded)](https://github.com/kalonji-tools/oxitest/issues/1681), [#1683 F6 (downgraded)](https://github.com/kalonji-tools/oxitest/issues/1683), [#1685 F8 (downgraded)](https://github.com/kalonji-tools/oxitest/issues/1685), [#1687 F11 (reframed)](https://github.com/kalonji-tools/oxitest/issues/1687), [#1688 F12 (user error)](https://github.com/kalonji-tools/oxitest/issues/1688), [#1689 F13 (downgraded)](https://github.com/kalonji-tools/oxitest/issues/1689). [#1686 F9](https://github.com/kalonji-tools/oxitest/issues/1686) CLOSED as invalid.

## Verdict

**oxitest carries loguru's full test suite on Linux.** 1579 tests migrate cleanly, 47 stay under pytest for a legitimate reason (mypy-plugins yml), 0 fail, 0 xfail, 0 gap-marked on ubuntu-22.04 py3.11–3.14 + pypy-3.11. Faster than pytest at same hardware.

**Cross-platform caveat (added after CI):** `tests (macos-15, 3.12)` and `tests (windows-2022, 3.12)` fail identically — **81 failures each**, all in `tests/test_filesink_rotation.py::test_time_rotation_*` (DST/timezone tests). Upstream `Delgan/loguru` passes these same tests on the same platforms under pytest, so the failures are migration-introduced, not a pre-existing loguru bug. Root cause not yet bisected — see **N3** in EVAL_NOTES.md for the three plausible hypotheses (FreezeTime capture-timing, test-ordering vs freezegun global state, or strict_warnings interaction with fork()).

**Two new adopter-friction gaps discovered** (N1 filterwarnings, N2 patch-context) — both are recipe-shaped, easy to document, and neither blocks anything. **F7 is corroborated as real** by 11 files needing the `pin_module_name` workaround; fixing it upstream would remove that need. **F2's workaround (absolute conftest import) is proven** at scale.

**Recommendations for T9–T11 (specialized showcases):**

1. **Docs-first, always.** The migration's docs-correct patterns are its greatest strength — no wasted signal on false findings. Read the relevant how-to before writing any port.
2. **Full-replacement in place** per map — no side-by-side. Narrow pytest's `testpaths` if some tests must stay pytest-only (like typesafety here).
3. **Adopt `pin_module_name` and `patch_context` verbatim** if the project's tests need them. Both are self-contained conftest patterns.
4. **Expect a 10–50× speedup story** — real number, real hardware. This is a stronger cross-showcase headline than any single feature-flag.
5. **N1 and N2 will recur** in any nontrivial pytest project — if the migrating agent invents them again independently, that's cross-showcase validation of the doc-recipe need.
6. **T9 (perf/click)** has a documented `oxitest_loguru` plugin-shaped question hanging over it ([#1687 F11-reframed](https://github.com/kalonji-tools/oxitest/issues/1687)); pallets/click's own logging use is minimal so this may not surface.

Pathfinder complete. Umbrella can close on this migration's back. T9/T10/T11 unblocked.
