# EVAL_NOTES — loguru pathfinder migration

Findings journal for the loguru showcase (map [`Wayfinder: oxitest usability showcase evaluation`](https://github.com/kalonji-tools/oxitest/issues/1660), pathfinder umbrella [`Migrate standard-features showcase (pathfinder)`](https://github.com/kalonji-tools/oxitest/issues/1668)).

**How this file was produced.** T8b baseline (config wiring, parity gate) was executed by an earlier agent session. The migration itself — commits `4824a4e` through `91f18e6` (16 commits, +7362/-3916 lines across 60 files) — was executed by a separate agent whose output this file evaluates. Prior T8c–T8f/T8g work was reset from the branch during the map's T8-post-mortem cleanup; those attempts do not appear in the current history.

## 2026-07-26 19:54 UTC — post-migration evaluation

Ticket: [T8g: Full-replacement pathfinder redo — port ONE loguru test file end-to-end](https://github.com/kalonji-tools/oxitest/issues/1690) (superseded in scope by the actual migration)

**Env verified:**
- oxitest: `3.0.0` (git `131dd9b` — v3.0.0 tag on `kalonji-tools/oxitest`, PyPI cp313 wheel)
- Python: `3.13.12` (nix `python313`, uv-managed venv)
- OS: NixOS, Linux kernel `6.12` (x86_64)
- Upstream commit (from T8a): `2a17be7` — `Delgan/loguru:master` at 2026-06-13
- Migration branch HEAD: `91f18e6` (2026-07-26 19:29 UTC)
- strict mode: `abort` (from T8b baseline; unchanged)

**Scope observed.** The migration is **the whole test suite** — not one file. `tests/typesafety/` stays under pytest (driven by `pytest-mypy-plugins`, which has no oxitest equivalent); everything else moved to oxitest. Both `pyproject.toml` and `.github/workflows/tests.yml` were restructured to reflect the split. CI Python matrix narrowed from 3.5–3.14 to 3.11+ (oxitest's floor).

### Measured results

**Test-count reconciliation (all runs from clean venv, uv-managed):**

| Source | Items | Passed | Skipped | Failed | xfailed |
|---|---|---|---|---|---|
| Pytest at T8b baseline (pre-migration) | 1692 | 1646 | 46 | 0 | 0 |
| Oxitest at HEAD `91f18e6` | 1625 | 1579 | 46 | 0 | 0 |
| Pytest at HEAD (typesafety only) | 47 | 47 | 0 | 0 | 0 |
| **Total at HEAD** | **1672** | **1626** | **46** | **0** | **0** |

Item delta: **1692 → 1672 = -20 items** across the whole suite. Not lost coverage in any observable sense — the migration re-shaped parametrize case counts and consolidated some tests. No functional regressions surfaced.

**Timings (Linux, cp313, uv-managed venv, warm cache):**

| Runner | Mode | Time | Items/s |
|---|---|---|---|
| Pytest (pre-migration) | serial | **79.8s** | 21.2 |
| Oxitest (post-migration) | serial (`--serial`) | **69.8s** | 23.3 |
| Oxitest (post-migration) | parallel (`-n 4`) | **31.5s** | 51.6 |

Oxitest wins even serially (~12%). Parallel is ~2.5× faster than the pytest baseline. Shared-fixture cache reported **1644/1645 hits (99%)** — the `check_env_variables` session-autouse fixture is genuinely paying for itself.

### Approach the migrating agent chose

**Full replacement in place** — the map's chartered strategy. Zero side-by-side `*_oxi.py` files. Every migrated test file is a rewrite of the pytest original at the same path. Pytest's `testpaths` narrowed to `["tests/typesafety"]` so it doesn't try to collect files it no longer understands (cleaner than `collect_ignore`).

**Fixtures live in `tests/conftest.py`.** Per [`use-fixtures.md`](https://kalonji-tools.github.io/oxitest/site/how-to/use-fixtures/) — the diagnostic misread the previous session flagged as **F6 [#1683](https://github.com/kalonji-tools/oxitest/issues/1683)** was never tripped. `fx = Fixtures()` and `common = Helpers()` at the top of conftest; downstream test files import types (`Writer`, `SinkWithLogger`, `FreezeTime`) from conftest by absolute name and consume fixtures via `Fixture[T]` annotations.

**Two new plain-module test helpers** — `tests/_naming.py` and `tests/_utils.py` — hold code that must exist at module-import time (parametrize case values, worker subprocess bootstraps) where the `oxitest.helpers` proxy isn't valid yet. This is a real architectural distinction the migration surfaced, well-documented in `_utils.py`'s docstring.

### Notable patterns invented on top of the docs

1. **`pin_module_name(globals(), "tests.<name>")`** — the clean F7 workaround. Called at the top of 11 test files (`test_activation`, `test_configure`, `test_reinstall`, `test_interception`, `test_coroutine_sink`, `test_formatting`, `test_pickling`, `test_add_option_filter`, `test_propagation`, `test_multiprocessing`, plus the helper module itself). Sets `namespace["__name__"] = name` and mirrors into `sys.modules[name]` so classes defined at module level still resolve back through `dataclasses`/`pickle`/`copy`. Opt-in per file — files that don't need it don't pay the cost.

2. **`patch_context()` helper wrapping `Patcher`** — pytest's `monkeypatch.context()` gives you a scoped `with` block whose patches revert at block exit. oxitest's `Patcher` auto-reverts at test end, not block end. The migration invented `patch_context()` in `tests/conftest.py` (lines 29–85) that provides the pytest-compatible semantic on top of oxitest's primitive. Used inside helpers like `simulate_f_globals_name_absent()` that need multiple scoped patches within a single test.

3. **`strict_warnings` autouse fixture** — replaces pytest's `[tool.pytest.ini_options] filterwarnings = [...]` config. Comment on line 105 of `pyproject.toml`: *"Warnings are turned into errors by the autouse 'strict_warnings' fixture in 'tests/conftest.py' rather than by configuration, since oxitest has no equivalent of pytest's 'filterwarnings' key."* — this is a real docs/config gap in oxitest.

4. **`INCOMPLETE_FRAME_CASES` / `INVALID_NAME_CASES` as module-level dict constants unpacked via `**`** — e.g. `@oxitest.parametrize(**INCOMPLETE_FRAME_CASES)`. Clean idiom for sharing parametrize case sets across multiple tests. Not explicitly documented, but follows naturally from `@oxitest.parametrize(name=case)` taking kwargs.

5. **Absolute conftest imports** — `from conftest import Writer` rather than `from .conftest import Writer`. Sidesteps F2 (relative-import blocker) by relying on the `sys.modules['conftest']` alias oxitest installs. Adopters need to know this is the right form; docs mention the alias but not the migration recipe.

### Findings this migration corroborates or refutes

- **F2 ([#1680](https://github.com/kalonji-tools/oxitest/issues/1680)) — CORROBORATED as real friction with clean workaround.** Every migrated file that needed a conftest symbol uses `from conftest import X` (absolute), never `from .conftest import X`. If the workaround were in the docs' migration guide, adopters wouldn't hit the wall the T8c pass documented.
- **F4 ([#1682](https://github.com/kalonji-tools/oxitest/issues/1682)) — NOT EXERCISED.** No collection failures under the migrated suite; the `--json`-empty-on-failure bug remains uncontradicted but wasn't retested. Still valid.
- **F7 ([#1684](https://github.com/kalonji-tools/oxitest/issues/1684)) — CORROBORATED as real; workaround exists.** 11 files (22% of migrated files) needed `pin_module_name`. Any adopter with tests that assert on `record.name`, run activation-matching, or use `{name}` in sink formats needs the workaround. Fixing the loader-side `__name__` synthesis (the issue's proposal) would remove the need for `pin_module_name` entirely.
- **F1 ([#1679](https://github.com/kalonji-tools/oxitest/issues/1679)) — CORROBORATED.** Post-audit narrowing to "wayfinder-internal T7 fix" holds; the migration didn't touch the `--report`/`--json` question because it never followed the T7 comment.
- **F6, F8, F13 (downgraded) — CONFIRMED downgraded.** The migration used docs-correct patterns and never tripped these; the diagnostics/behaviors flagged in the first pass really were user error against docs.
- **F9 ([#1686](https://github.com/kalonji-tools/oxitest/issues/1686), closed invalid) — REMAINS INVALID.** The migration is proof that a real pytest→oxitest migration is achievable using the existing `migrate-from-pytest.md`. But (see below) the migration also invented `pin_module_name` and `patch_context` on top of the docs — an "extended migration recipes" doc would help.

### New findings surfaced by this migration

Two above-threshold candidates, both docs/UX gaps:

#### N1 — No `filterwarnings` config in `[tool.oxitest]`; forces autouse-fixture workaround

Pytest lets you configure warning filters declaratively:
```toml
[tool.pytest.ini_options]
filterwarnings = ["error", "ignore::DeprecationWarning:asyncio.*"]
```

Oxitest has no equivalent. To match "warnings become errors" behavior, the migration wrote an autouse fixture that manually uses `warnings.catch_warnings()` + `warnings.simplefilter("error")` + per-message filter rules. Every migrating pytest project with `filterwarnings` config will re-derive this fixture.

**Above threshold.** Two options: (a) add `[tool.oxitest] filterwarnings = [...]` config parity, or (b) document the autouse-fixture pattern as a canonical migration recipe.

#### N2 — No `Patcher.context()` for pytest-`monkeypatch.context()` parity

`oxitest.Patcher` auto-reverts at test end. Pytest's `monkeypatch.context()` reverts at block end — useful for helpers that install and remove multiple patches within a single test. The migration invented `patch_context()` in conftest (57 lines wrapping `Patcher`'s API). Every adopter with `monkeypatch.context()` usage will re-invent similar plumbing.

**Above threshold.** Options: (a) add `Patcher.context()` (or `.scope()`) yielding a scoped patch handle, or (b) document the recipe.

Zero code-fix bugs surfaced by the migration itself. All 1579 items pass under oxitest with no xfails and no gap-marked tests.

### Small residues (not filed)

- `pyproject.toml` line 100 has `show_locals = true` — an option not documented in [`reference/configuration.md`](https://kalonji-tools.github.io/oxitest/site/reference/configuration/) as of this evaluation. May be a valid option not yet in docs, or a stale key that's silently ignored. Runs are green either way.
- `.gitignore` correctly excludes `.oxitest_cache/` (line 113) and `results/` (line 110). Small polish the earlier passes missed.

### What I did NOT verify

- **I did not audit every migrated file line-by-line.** Random-spot-checks of `test_activation.py`, `test_add_option_catch.py`, plus the whole conftest and helpers, showed docs-correct patterns and consistent idioms. The 60-file diff was not exhaustively reviewed.
- **The 20-item test-count delta is unaccounted individually.** Total counts add up (1692 → 1672 is a 1.2% variance); no test file lost more than ~2–3 items to restructuring based on the spot-checks. Not a regression on any observable dimension, but not proved lossless either.
- **CI wasn't run.** The `.github/workflows/tests.yml` restructure looks correct (`tests` job on py3.11–3.14 running oxitest + coverage; new `typesafety` job on py3.12 running pytest-mypy-plugins via tox), but the actual GitHub Actions matrix wasn't triggered.
- **No cross-platform check.** All runs on NixOS Linux; the CI matrix includes `windows-2022` + `macos-14` per the workflow file but that wasn't exercised locally.

### CI addendum (2026-07-26, post-local-eval)

Local eval was Linux-only. CI on kalonji-tools/loguru surfaced platform-specific regressions the local pass missed:

| Job | Result |
|---|---|
| tests (ubuntu-22.04, 3.11) | ✅ pass |
| tests (ubuntu-22.04, 3.12) | ✅ pass — 1576 passed, 46 skipped |
| tests (ubuntu-22.04, 3.13) | ✅ pass |
| tests (ubuntu-22.04, 3.14) | ✅ pass |
| tests (ubuntu-22.04, pypy-3.11) | ✅ pass |
| tests (macos-15, 3.12) | ❌ **81 failed · 1489 passed · 52 skipped** |
| tests (windows-2022, 3.12) | ❌ **81 failed · 1494 passed · 70 skipped** |
| typesafety | ✅ pass |

**Failure pattern:** identical on both macOS and Windows — all 81 failures are in `tests/test_filesink_rotation.py::test_time_rotation_*` (DST/timezone-driven rotation tests). Same assertion shape across the board: `content = ['']` when expected `["a\n", "b\nc\n", "d\n", "e\n"]` — meaning the file **isn't rotating** when the frozen clock advances past a rotation boundary. Ubuntu 3.12 passes all these same tests.

**Reference point:** Upstream `Delgan/loguru`'s CI ([run 30181113423](https://github.com/Delgan/loguru/actions/runs/30181113423)) passes `tests (macos-15, 3.12)` and `tests (windows-2022, 3.12)` on the SAME source snapshot before the migration. So the DST tests **do work under pytest** on macOS/Windows 3.12; the failures are introduced by the migration to oxitest.

### Finding N3 — Migration introduces platform-specific regression in `test_time_rotation_*` (macOS + Windows)

**Above threshold** — but categorization requires more investigation. Three plausible root causes, in order of likelihood:

1. **`FreezeTime` port has a subtle capture-timing bug.** Upstream's fixture captures `freezegun.api.fake_localtime` at fixture invocation time; the migrated `FreezeTime.__init__` captures it at instance creation. Under `spawn`-based multiprocessing (default on macOS/Windows), fresh worker processes could see a differently-patched module-level `fake_localtime` at instance creation than a fresh pytest process would.
2. **oxitest test-ordering vs pytest test-ordering interacts with freezegun's global state.** oxitest sorts tests using cached timings (`.oxitest_cache/timings.json`) or file order; pytest sorts alphabetically by default. A stateful test running earlier under oxitest could leave freezegun in a state that breaks later DST tests. Ubuntu happens to avoid the bad ordering; macOS/Windows hit it.
3. **`strict_warnings` autouse fixture** turns fork-related DeprecationWarnings into errors, but only when `fork()` is being called — which is more common on macOS. The macOS log shows extensive `use of fork() may lead to deadlocks` warnings that pytest may have been suppressing differently.

**Impact:** Blocks a clean cross-platform migration story. If this were a real adopter's project, they'd have to either debug the DST regression or ship with red macOS/Windows CI.

**What would confirm oxitest-limitation vs migration-bug:**
- Bisect the 16 migration commits to find the one that broke DST rotation on macOS
- Reproduce locally on macOS/Windows (not possible from this NixOS host)
- Try running the migrated suite under an oxitest debug flag that fixes test order (e.g., `--schedule` variants)
- Isolate `test_filesink_rotation.py` under `--serial` and see if it still fails

**Filing recommendation:** File as a **showcase-eval** issue on oxitest AFTER a bisect narrows the cause. Filing now without a repro would be another speculative-finding mistake (see the T8 post-mortem lesson). Track it as an EVAL_NOTES entry until then.

### Verdict

**Real migration on Linux.** 1579 items green, faster than pytest, docs-correct patterns. **Not yet a full-platform migration** — macOS + Windows have an 81-test regression in the DST rotation suite that upstream loguru does NOT have under pytest. Two above-threshold docs-shaped findings (N1 filterwarnings, N2 patch-context) plus one under-investigation regression (N3).

The map's "learning phase" framing was correct — the first T8 pass produced anti-signal; this second-agent pass produced real signal AND surfaced a real cross-platform bug that only end-to-end CI catches. Pathfinder umbrella should NOT close until N3 is at least bisected.

T9/T10/T11 can proceed but should note the cross-platform-verification requirement in their exit criteria.
