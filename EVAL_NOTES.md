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

#### N2 — Patcher ships in the wrong shape: fixture-only, but adopters need a block-scoped helper

**Original framing** (add `Patcher.context()` for pytest-`monkeypatch.context()` parity) was too narrow. Post-hoc code inspection revealed the deeper issue:

**Usage-data proof of shape mismatch:**
```
$ grep -rn "patch_context\|helpers.common.patch_context" tests/ | wc -l
41
$ grep -rn " Patcher\b\|Fixture\[Patcher\]\|patch:.*Patcher" tests/ | wc -l
0
```

The `Patcher` fixture went **entirely unused** in the migrated codebase. Every one of 41 patching sites reached for the block-scoped `helpers.common.patch_context()` shape the migration invented.

**Concrete API-surface gaps between built-in `Patcher` and the invented `patch_context()`:**

| Concern | `Patcher` (built-in fixture) | `patch_context()` (invented helper) |
|---|---|---|
| Lifetime | Test-scoped (undone at teardown) | Block-scoped (undone at `with` exit) |
| `setattr(raising=False)` | ❌ Always raises if attr missing | ✅ |
| `delattr` | ❌ | ✅ |
| `setitem` / `delitem` (arbitrary mappings) | ❌ | ✅ (and `setenv` is derived from `setitem`) |
| `chdir` | ✅ | ❌ (unused in loguru) |

The lifetime mismatch is dominant. Nested-block patching — install patch, verify with-patch, exit scope, verify without-patch, all within one test — is impossible with `Patcher`'s test-scoped API.

**Design insight:** oxitest built-ins split cleanly by identity:
- **Fixtures** carry state across a test's lifetime; injected as parameters; bound to teardown.
- **Helpers** are inline callables/context-managers invoked in the test body; no lifecycle coupling.

Pytest's `monkeypatch` is BOTH shapes — injected as fixture AND has `.context()` for scoping. Confusing but pragmatic. oxitest split the shapes but shipped only the fixture form.

**Above threshold. Reframed options:**

1. **Ship `patcher` as a built-in helper** (`with helpers.oxi.patcher() as p: ...`) — matches the dominant usage shape. Keep `Patcher` fixture for the whole-test-scoped case if it has adopters elsewhere.
2. **Broaden the API surface** either way — `raising=` kwarg, `setitem`/`delitem`/`delattr` — matching pytest-monkeypatch parity.

This isn't a missing method. It's the shape mismatch itself: **oxitest shipped the less-common shape as the only shape.**

See also the follow-on wayfinder map on cross-cutting Fixture-vs-Helper identity audit (filed alongside this eval).

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

## Deep audit addendum (2026-07-26) — fine-tooth-comb pass across all 60 files

Prompted by user directive: "look at the features that we have today, look at the features that were used, ask why previous agent chose to resolve it like it did? if created it's own question our built-in? why did author/dev chose this way over our available features?" — done systematically.

### Method

1. Enumerated oxitest's full public API from `oxitest/__init__.py:__all__` (42 exported names).
2. Cataloged every INVENTION in `tests/conftest.py` (423 lines), `tests/_utils.py` (70 lines), `tests/_naming.py` (23 lines).
3. Counted usage of every oxitest built-in fixture, mark, helper across all 60 migrated test files.
4. Cross-referenced original pytest usage (at commit `2a17be7`) with oxitest usage (at HEAD `91f18e6`) at the per-test-function-parameter granularity.

### Usage census (oxitest built-in fixtures)

| Built-in | Uses across 60 files |
|---|---|
| `TempDir` | 101 tests (parameter) |
| `StdCapture` | 108 tests (parameter) |
| `LogCapture` | 2 tests (both in `test_coroutine_sink.py`) |
| **`Patcher`** | **0 tests** — replaced by `patch_context` helper (see N2) |
| **`WarnCapture`** | **0 tests** — `oxitest.warns()` context manager covers assertion case (3 uses) |
| **`FdCapture`** | **0 tests** — loguru writes at Python stream level; StdCapture suffices |
| **`TempDirFactory`** | **0 tests** — no session-scoped temp dir need |
| **`TestContext`** | **0 tests** — `Yields[None]` covers teardown; `addfinalizer` unused |

### Usage census (oxitest APIs)

| API | Uses |
|---|---|
| `Fixture[T]` (type-annotated user fixtures) | 297 (244 `Writer` + 52 `FreezeTime` + 1 `Type[SinkWithLogger]`) |
| `@oxitest.parametrize` | 274 |
| `oxitest.raises(...)` | 116 |
| `oxitest.partial(...)` (composed parametrize) | 89 |
| `oxitest.mark.skip(...)` (all 71 `mark.*` uses are skip) | 71 |
| `oxitest.skip()` (imperative) | 6 |
| `oxitest.warns(...)` | 3 |
| **`FixtureRef[T]`** | **0** — see finding N4 below |
| **`oxitest.arrange(...)`** | **0** — autouse fixtures used instead |
| **`oxitest.approx(...)`** | **0** — loguru has no float-comparison tests |
| **`oxitest.importorskip(...)`** | **0** — dev-deps guaranteed installed |

### User-defined fixture surface (7 total on `fx`)

All 7 are in `tests/conftest.py`:

| Fixture | Type | Notes |
|---|---|---|
| `writer` | function-scope | Returns fresh `Writer()` — loguru sink for tests |
| `sink_with_logger` | function-scope | Returns `Type[SinkWithLogger]` class — tests instantiate per case |
| `freeze_time` | function-scope | Returns fresh `FreezeTime()` instance |
| `check_env_variables` | **`autouse=True, shared=True`** | Session-warn on `LOGURU_*` env vars |
| `strict_warnings` | `autouse=True` | Warnings-as-errors (see N1) |
| `reset_logger` | `autouse=True` | Loguru state reset between tests |
| `reset_multiprocessing_start_method` | `autouse=True` | Global multiprocessing state reset |

### Helper surface (5 on `common`)

| Helper | Uses | Notes |
|---|---|---|
| `check_dir` | 90 | Assert on directory contents (rotation tests) |
| `patch_context` | 36 direct + 5 in conftest = 41 total | Block-scoped patching (see N2) |
| `make_logging_logger` | 18 | Stdlib logger setup for loguru→stdlib bridging tests |
| `default_threading_excepthook` | 5 | Thread-excepthook context manager |
| `simulate_f_globals_name_absent` / `simulate_no_frame_available` / `simulate_missing_frame_lineno` | via string dispatch (~6 total) | Loguru frame-inspection simulations |

### Original-vs-migrated pytest concepts (per test-function parameter counts)

| Concept | Pytest (2a17be7) | Oxitest (HEAD) | Assessment |
|---|---|---|---|
| Custom fixtures | 19 `@pytest.fixture` | 7 `@fx.fixture` | Consolidated: some pytest fixtures became helpers or `Yields[T]` inline |
| Fixture with `params=[...]` (parametrized) | 2 | **0 FixtureRef** — replaced by string-dispatch helpers | **N4** |
| Fixture with `scope="session"` | 1 (`check_env_variables`) | 1 (same, now `shared=True`) | 1:1 |
| Fixture with `scope="module"` | 1 (`test_filesink_permissions`) | Collapsed to `shared=True` | Per docs, module scope collapses to shared |
| `tmp_path` param | 123 tests | 101 `tmp: TempDir` tests | -22 (some tests consolidated) |
| `capsys` param | 115 tests | 108 `cap: StdCapture` tests | -7 |
| `caplog` param | 4 tests | 2 `log: LogCapture` tests | -2 |
| `monkeypatch` param | 55 tests | **0 `patch: Patcher` params + 36 block-scoped `patch_context()`** | See N2 — shape shifted |
| `@pytest.mark.parametrize` | 259 | 274 `@oxitest.parametrize` | ≈ (some added via composition) |
| `@pytest.mark.skipif` / `.skip` | 81 | 71 `@mark.skip(when=…)` | ≈ (unified per docs) |
| `@pytest.mark.xfail` | 1 | 0 | -1 (single case rewritten?) |
| `pytest.raises` | 116 | 116 `oxitest.raises` | 1:1 exact |
| `pytest.warns` | 3 | 3 `oxitest.warns` | 1:1 exact |
| `pytest.fixture(params=[...])` | 2 | 0 FixtureRef | Replaced (N4) |

### New findings from the deep audit

Beyond N1 (filterwarnings) and N2 (Patcher shape) already filed:

#### N4 — `FixtureRef[T]` unused because helpers are the natural shape for scoped setup

pytest's `@pytest.fixture(params=[...])` parametrizes over fixture strategies. oxitest docs propose `FixtureRef[T]` in dataclass parametrize cases as the equivalent. **Migration used it 0 times.**

Instead: the migration dispatches over helper names as strings:

```python
INCOMPLETE_FRAME_CASES = {
    "no_globals_name": IncompleteFrameCase(simulate="simulate_f_globals_name_absent"),
    "no_frame": IncompleteFrameCase(simulate="simulate_no_frame_available"),
}

@oxitest.parametrize(**INCOMPLETE_FRAME_CASES)
def test_x(simulate: str, ...) -> None:
    with getattr(helpers.common, simulate)():
        ...
```

**Why not FixtureRef?** Because the "simulate" strategies are helpers (context managers used inside test body with `with`), not fixtures. Converting them to fixtures would:
- Force implicit setup/teardown (loses visible scope in test body)
- Move the block-scope semantic to a fixture, which is test-scoped (see N2)

**Above threshold.** Same shape family as N2 — the fixture-only parametrization surface misses the case where an adopter wants to parametrize over HELPERS (block-scoped, inline-visible setup). Options:

1. `HelperRef[T]` — a parametrize case field that resolves to a helper, invoked as context manager
2. Document the string-dispatch idiom as a canonical pattern (with type-safety caveats)
3. Broaden FixtureRef semantics to allow "fixture OR helper" targets

Related to Patcher / N2 and the wayfinder map on Fixture-vs-Helper identity ([#1697](https://github.com/kalonji-tools/oxitest/issues/1697)) — this is a third data point that the shape distinction has under-explored edges.

#### N5 — `oxitest.helpers` proxy inaccessible at import time / in subprocess workers → forces file split

Migration ships **two separate modules** for stateless test utilities:

- `tests/conftest.py` — `common = Helpers()` + `@common.helper` decorators for session-time helpers accessed via `oxitest.helpers.common.X()`
- `tests/_utils.py` — plain module-level functions for utilities needed at:
  - Parametrize case build time (import-time evaluation before session)
  - Worker subprocess functions (different process, no session)

The `_utils.py` docstring explicitly explains WHY:
> Everything here is plain module-level code rather than a `conftest.py` helper because the `oxitest.helpers` proxy only resolves while a session is running, and these are needed in two places where that is not true: `@oxitest.parametrize` case values, which are built as the test module is imported, and worker functions executed in a child process.

**Above threshold** — this is a real architectural constraint on helper design that adopters WILL rediscover the hard way if not documented. Options:

1. **Docs fix**: add a recipe/section in `use-fixtures.md` (or a new `share-test-helpers.md`) explaining the session-time-only nature of the helpers proxy, and recommending the plain-module split with `tests/_utils.py` naming convention.
2. **API fix**: make the helpers registration mechanism work at import time (e.g., a static registry that doesn't require a session). Bigger change.

Docs fix is cheaper and probably enough — the pattern is fine once you know it, just non-obvious.

#### Non-findings (built-ins legit-unused for this project)

- **`FdCapture` (0 uses)** — loguru writes via Python stream API, never fd-direct. Legit unused. Not a shape issue.
- **`TempDirFactory` (0 uses)** — no session-shared temp-dir need. Legit unused.
- **`TestContext` (0 uses)** — `Yields[T]` fixture teardown was preferred over `ctx.addfinalizer()` for all cleanup. Style choice, not a shape issue.
- **`WarnCapture` (0 uses)** — `oxitest.warns(Category, match=...)` context manager covers the 3 warning-assertion cases loguru has. No test needs aggregate warning collection. Legit unused for this project.
- **`oxitest.arrange` (0 uses)** — autouse fixtures used instead. Both patterns exist for good reasons; migration reached for one. Style choice.
- **`oxitest.approx` (0 uses)** — loguru has no float-tolerance comparisons. Legit unused.
- **`oxitest.importorskip` (0 uses)** — dev-deps are guaranteed installed. Legit unused.

### Interpretation

**Two of the eight built-in fixtures are shipped in a shape adopters don't reach for** — `Patcher` (see N2) and (weakly) `WarnCapture`. The others are either idiomatic for their intended purpose or legitimately unused because loguru doesn't need them.

**One parametrize pattern is missing** — the ability to parametrize over helpers (see N4). Adopters invent string-dispatch workarounds.

**One architectural constraint is under-documented** — the session-time-only nature of `helpers` forces a plain-module split (see N5).

All three findings converge on the same theme: **oxitest's Fixture-vs-Helper identity distinction has under-explored edges**. The wayfinder map [`Wayfinder: fixture-vs-helper identity for oxitest built-ins` #1697](https://github.com/kalonji-tools/oxitest/issues/1697) is the right place to grill these — N4 and N5 should be added to its "Not yet specified" fog as evidence.

---

## T8 conclusion — re-verified against oxitest 4.0.0 (2026-08-13)

The fork was migrated and concluded against **oxitest 3.0.0**. This section
re-runs it against **4.0.0**, the release carrying the fixes for the two
findings this showcase filed and that were closed `COMPLETED`
([#1680](https://github.com/kalonji-tools/oxitest/issues/1680),
[#1684](https://github.com/kalonji-tools/oxitest/issues/1684)).

### Result parity

| oxitest | Result |
|---|---|
| `3.0.0` (as concluded) | **1579 passed · 46 skipped · 20 warnings** |
| `4.0.0` (after the changes below) | **1579 passed · 46 skipped · 20 warnings** |

Identical. The pin in `pyproject.toml` is now `oxitest==4.0.0`.

### N6 — 3.0.0 → 4.0.0 removed the helper surface, and the suite did not load

**Above threshold.**

`oxitest 4.0.0` no longer exports `Helpers` or the `helpers` proxy. The first
run on 4.0.0 did not reach a single test:

```
Failed to load conftest fixtures: ImportError: cannot import name 'Helpers' from 'oxitest'
```

Blast radius in this fork: **`conftest.py` plus 21 test files**, and **150
call sites** through `helpers.common.<name>` — 90 `check_dir`, 36
`patch_context`, 18 `make_logging_logger`, 5 `default_threading_excepthook`,
1 `simulate_missing_frame_lineno`.

Five further sites resolved a helper **by name string**, `getattr(helpers.common,
simulate)()`, so a per-name import would not have covered them.

**The migration:** the seven registered helpers became plain module-level
functions in `conftest.py`, and every call site now reads `conftest.<name>`.
That one form covers the static calls and the `getattr` sites together.

**The retirement is right** — the proxy resolved through `__getattr__` to `Any`,
so a type checker saw nothing at any call site. **The finding is that a major
version removed a surface with no shim, no deprecation warning, and no entry in
the migration guide.** An adopter meets it as an `ImportError` at conftest load,
with nothing naming the replacement.

### N7 — the module-identity workaround is STILL required on 4.0.0

**This is the conclusion this re-verification was run to reach, and the answer
is no.**

`tests/_naming.py`'s `pin_module_name` exists because oxitest loads a test module
under a synthetic name, and loguru derives a record's `name` field from the
calling module's `__name__`. #1680 and #1684 both closed `COMPLETED`, so the
question was whether the shim could be deleted.

**It cannot.** Removing `pin_module_name` from all 10 consuming files:

| Scope | Result without the shim |
|---|---|
| `tests/test_activation.py`, serial | **6 failed · 27 passed** |
| whole suite | **the run did not finish inside 550 s** |

The 6 failures are the same 6 that T8g recorded as xfails under #1684.

**Measured on 4.0.0**, a test module still sees a synthetic name:

```
__name__='_oxitest_collect_9a4a63aec39d'  in_sys_modules=True
```

**What did change is the second half.** The synthetic name is now registered in
`sys.modules`, which is what #1680 fixed — machinery that resolves a class back
to its defining module (`dataclasses`, `pickle`, `copy`) works. **The name
itself is still not the dotted package name**, so any suite that asserts on
`__name__` still needs its own shim.

`pin_module_name` therefore does two jobs, and only one of them is now
redundant:

| Job | State on 4.0.0 |
|---|---|
| Set `__name__` to the dotted name | **still required** |
| Register the alias in `sys.modules` | **now redundant** — oxitest registers the synthetic name itself |

⚠️ **The whole-suite hang is not explained.** Single-file removal fails fast and
cleanly; whole-suite removal did not finish. The suite has multiprocessing and
pickling tests, and pickling needs a resolvable module name, so a deadlock is
plausible — **but this was not established, and it is recorded as unverified.**
