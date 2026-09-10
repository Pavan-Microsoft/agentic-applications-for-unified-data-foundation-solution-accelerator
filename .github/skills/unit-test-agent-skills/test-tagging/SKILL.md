---
name: test-tagging
description: >
  Classifies existing tests by standard traits and reports their distribution.
  MUST USE to categorize/tag/label tests, compare happy vs error paths, audit
  the test mix, or describe coverage shape by test type. Read bodies when names
  mislead. Apply canonical attributes; otherwise report only. Supports .NET
  (MSTest/xUnit/NUnit/TUnit) and Python (pytest/unittest). DO NOT USE for
  test-quality audits, executed coverage or CRAP, behavioral gaps, writing
  tests, or migration.
license: MIT
---

# Test Trait Tagging

Analyze an existing .NET or Python test suite and apply a standardized set of trait tags to each test method, giving teams visibility into their test distribution (positive vs. negative, critical-path coverage, smoke tests, etc.).

> **Language-specific guidance**: Call the `test-analysis-extensions` skill to discover available extension files, then read the file matching the target codebase (`extensions/dotnet.md` for .NET, `extensions/python.md` for pytest/unittest). The extension file documents framework-specific tag attributes and a "tag-support capability" that drives whether this skill modifies source files or only emits a report. If the codebase is neither .NET nor Python, decline the request and report that only .NET and Python are supported.

## When to Use

- Auditing a test project to understand the mix of test types
- Adding trait attributes to untagged tests
- Generating a summary report of trait distribution across a test suite
- Reviewing whether critical paths have sufficient coverage

## When Not to Use

- Writing new tests from scratch (use `code-testing-agent` for .NET or Python, or `writing-mstest-tests` for MSTest)
- Running or filtering tests (use `run-tests` for .NET; `pytest` directly for Python)
- Migrating between test frameworks
- General quality, smell, flakiness, or assertion audits (use `test-anti-patterns` or the matching analysis skill)
- Diagnostic .NET executed line/branch/Cobertura interpretation or project-wide CRAP risk (use `coverage-analysis`); raw coverage collection (use `run-tests` for .NET, `coverage.py`/`pytest-cov` for Python)
- CRAP analysis for a named method, class, or file (use `crap-score`)
- Behavioral gaps where a test would survive broken production logic (use `test-gap-analysis`)

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Test project or files | Yes | Path to the test project, folder, or specific test files to analyze |
| Scope | No | `tag` (apply canonical attributes, or a confirmed project convention), `audit` (report only), or `both` (default: `both`).Frameworks declared `report-only` always emit a report; `convention-based` frameworks edit only after the user confirms the convention. |
| Framework | No | Auto-detected. Override when detection fails. |

## Trait Taxonomy

Use exactly these trait names and values. Do not invent new trait values outside this table.

| Trait Value | Meaning | Heuristics |
|-------------|---------|------------|
| `positive` | Verifies expected behavior under normal/valid conditions | Asserts success, valid output, expected state, no exceptions for valid input |
| `negative` | Verifies correct handling of invalid input, errors, or edge cases | Asserts exceptions, error codes, validation failures, rejects bad input |
| `boundary` | Tests limits, thresholds, empty/null/None inputs, min/max values | Operates on `0`, `-1`, `int.MaxValue` / `sys.maxsize`, empty string, `null` / `None`, empty collection, boundary of valid range |
| `critical-path` | Core workflow that must never break; breakage blocks users | Tests the primary success scenario of a key public API or user-facing feature |
| `smoke` | Quick sanity check that the system is operational | Fast, no complex setup, verifies basic wiring (e.g., service resolves, endpoint returns 200) |
| `regression` | Reproduces a specific previously-reported bug | References a bug ID, issue number, or describes a fix in its name or comments |
| `integration` | Crosses process, network, or persistence boundaries | Uses real database, HTTP client, file system, external service, or multi-component setup |
| `end-to-end` | Full user workflow spanning the entire application stack | Exercises a complete scenario from entry point to final result, distinct from single-boundary `integration` |
| `performance` | Validates timing, throughput, or resource consumption | Asserts on elapsed time, memory, allocations, or uses benchmark harness (BenchmarkDotNet, pytest-benchmark) |
| `security` | Verifies authentication, authorization, input sanitization, or secrets handling | Tests for SQL injection, XSS, CSRF, unauthorized access, token validation, permission checks |
| `concurrency` | Validates thread safety, parallelism, or async correctness | Uses `Task.WhenAll` / `Parallel.ForEach` / `SemaphoreSlim` / `Interlocked` (.NET); `asyncio.gather` / `threading.Lock` / `multiprocessing` (Python); reproduces race conditions |
| `resilience` | Tests retry logic, timeouts, circuit breakers, or graceful degradation | Asserts behavior under transient failures, network drops, or service unavailability (e.g., Polly for .NET, tenacity for Python) |
| `destructive` | Mutates shared or external state that is hard to roll back | Deletes records, drops resources, modifies global config — useful for CI isolation decisions |
| `configuration` | Verifies settings loading, defaults, environment behavior | Tests missing config keys, invalid values, environment variable fallbacks, options validation |
| `flaky` | Known to intermittently fail (meta-tag for test health tracking) | Mark tests the team knows are unreliable; used to quarantine or prioritize stabilization |

A single test may have **multiple traits** (e.g., both `negative` and `boundary`). At minimum, every test should receive one of `positive` or `negative`.

## Workflow

### Step 1: Detect the language, framework, and tagging capability

Identify the codebase's language and test framework. Call the `test-analysis-extensions` skill and read the matching extension file. Supported capabilities:

- **.NET** — `auto-edit`. MSTest `[TestCategory("...")]`, xUnit `[Trait("Category", "...")]`, NUnit `[Category("...")]`, TUnit `[Property("Category", "...")]`.
- **pytest** — `auto-edit` via `@pytest.mark.<name>` (also requires registering the marker in `pytest.ini` / `pyproject.toml` to silence `PytestUnknownMarkWarning`).
- **Plain `unittest.TestCase`** (no pytest) — `report-only`. `unittest` has no canonical trait attribute.

### Step 2: Scan existing traits

Check which tests already have trait attributes. Use the loaded language extension as the source of truth:

| Framework | Existing Attribute | Example |
|-----------|--------------------|---------|
| MSTest | `[TestCategory("...")]` | `[TestCategory("positive")]` |
| xUnit | `[Trait("Category", "...")]` | `[Trait("Category", "positive")]` |
| NUnit | `[Category("...")]` | `[Category("positive")]` |
| TUnit | `[Property("Category", "...")]` | `[Property("Category", "positive")]` |
| pytest | `@pytest.mark.<name>` | `@pytest.mark.positive` |

Record which tests already have tags to avoid duplication.

### Step 3: Classify each test method

Build one canonical inventory containing each discovered test exactly once.
Record the test identifier, behavioral classification, and traits in that
inventory; use the same rows for source edits, per-test reporting, totals, and
distribution counts. Do not hand-count a separate denominator. Before
publishing, reconcile the reported total with the number of inventory rows and
verify that every row contributes to each displayed trait count.

For each test method without traits, analyze:

1. **Method name** -- names containing `Invalid`, `Fail`, `Error`, `Throw`, `Reject`, `BadInput`, `Null`, `None`, `Negative`, `raises_`, `_throws_`, `_returns_error` suggest `negative`
2. **Assertion type** -- `Assert.ThrowsException` (MSTest) / `Assert.Throws` (xUnit) / `Assert.That(..., Throws.TypeOf<T>())` (NUnit) / `pytest.raises` / `self.assertRaises` (unittest) suggest `negative`
3. **Input values** — `null` / `None`, `""`, `0`, `-1`, `int.MaxValue` / `sys.maxsize`, empty collections suggest `boundary`
4. **Setup complexity** — minimal setup with basic assertions suggests `smoke`; external dependencies (file/db/net/env) suggest `integration`
5. **Comments and names** — references to issue numbers or "regression" / "bug" / "fix for #..." suggest `regression`
6. **Timing assertions** — `Stopwatch`, `BenchmarkDotNet`, elapsed-time checks (.NET); `pytest-benchmark` fixtures, `time.perf_counter()` deltas (Python) suggest `performance`
7. **Feature centrality** — tests on primary public API entry points or critical user workflows suggest `critical-path`
8. **Security patterns** -- validates auth, checks permissions, sanitizes input, tests for injection, handles tokens/secrets suggest `security`
9. **Parallel/async constructs** -- `Task.WhenAll` / `Parallel.ForEach` / `SemaphoreSlim` / `Interlocked` (.NET); `asyncio.gather` / `threading.Lock` / `multiprocessing` (Python) suggest `concurrency`
10. **Fault injection** -- simulates failures, tests retries, timeouts, or circuit breakers (Polly, tenacity) suggest `resilience`
11. **State mutation** -- deletes external records, drops resources, modifies shared/global state suggest `destructive`
12. **Full-stack flow** -- test spans entry point through data layer to final response, covering a complete user scenario suggest `end-to-end`
13. **Config/settings** -- loads configuration, tests missing keys, validates options, checks environment variables suggest `configuration`
14. **Known instability** -- test has skip / ignore annotations with comments about flakiness (`[Ignore]`, `@pytest.mark.skip(reason="flaky")`, `unittest.skip`), or names contain "flaky" / "intermittent" suggest `flaky`
15. **Default** -- if the test verifies a normal success path, tag `positive`

When in doubt between `positive` and `negative`, read the assertion: if it asserts success -> `positive`; if it asserts failure -> `negative`.

### Step 4: Apply trait attributes (or report only)

For **.NET** (`auto-edit`), add the appropriate attribute to each test method. Place trait attributes adjacent to the existing test attribute:

**MSTest:**
```csharp
[TestMethod]
[TestCategory("negative")]
[TestCategory("boundary")]
public void Parse_NullInput_ThrowsArgumentNullException() { ... }
```

**xUnit:**
```csharp
[Fact]
[Trait("Category", "positive")]
[Trait("Category", "critical-path")]
public void CreateOrder_ValidItems_ReturnsConfirmation() { ... }
```

**NUnit:**
```csharp
[Test]
[Category("regression")]
[Category("negative")]
public void Calculate_OverflowInput_ReturnsError() // Fix for #1234
{ ... }
```

For **pytest** (`auto-edit`):

```python
@pytest.mark.negative
@pytest.mark.boundary
def test_parse_none_input_raises_value_error():
    ...
```

Also register the marker in `pytest.ini` or `pyproject.toml`:

```ini
[pytest]
markers =
    positive: verifies expected behavior under normal conditions
    negative: verifies correct handling of invalid input or errors
    boundary: tests limits, thresholds, and edge values
```

For plain **`unittest.TestCase`** tests (no pytest markers available), do NOT modify source files. Emit a report-only Markdown table mapping each test method to its suggested tags, and recommend adopting pytest markers if the team wants persistent, filterable tags.

### Step 5: Generate trait summary

After tagging, produce a summary table. Include only traits with a non-zero
count unless the user asks for the full taxonomy; zero-filled rows obscure the
suite's actual shape. For a small report-only suite, keep the per-test mapping
and non-zero distribution together rather than expanding into a dashboard.

```
## Trait Distribution

| Trait         | Count | % of Total |
|---------------|-------|------------|
| positive      |    50 |      64.1% |
| negative      |    28 |      35.9% |
| boundary      |     8 |      10.3% |
| critical-path |    12 |      15.4% |
| **Total tests** | **78** | -- |

Note: Percentages exceed 100% because tests can have multiple traits.
```

Include observations such as:
- Ratio of positive to negative tests
- Whether critical-path tests exist for key public APIs
- Any tests that could not be confidently classified (list them for manual review)

## Validation

- [ ] Every test method has at least one trait classification (`positive` or `negative` at minimum) — in the report for `report-only` cases, or as an attribute for `auto-edit` cases
- [ ] The total equals the per-test inventory count, and displayed trait counts were derived from that inventory
- [ ] No invented trait values outside the taxonomy table
- [ ] Existing trait attributes were preserved, not duplicated
- [ ] The trait summary table was generated
- [ ] For `auto-edit` frameworks, the project still builds / tests still discover after changes (`dotnet build` / `pytest --collect-only` / `mvn test-compile` / `go vet ./...` / `cargo check --tests` / `npm run test:list` / `Invoke-Pester -PassThru -Skip` / equivalent)
- [ ] For `report-only` frameworks, no source files were modified
- [ ] For `convention-based` frameworks, edits were applied ONLY when a project convention was confirmed

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Guessing traits without reading the test body | Always read assertions and setup to classify accurately |
| Tagging a test only as `boundary` without `positive`/`negative` | Every test should also be `positive` or `negative` -- `boundary` is additive |
| Using the wrong attribute syntax for the detected framework | Match the attribute style to the loaded language extension (don't put `[TestCategory]` in an xUnit project or `@pytest.mark.x` in a plain `unittest` test) |
| Duplicating an existing category attribute | Check for pre-existing traits in Step 2 before adding |
| Over-tagging as `critical-path` | Reserve for tests on primary public entry points, not every helper |
| Emitting `@pytest.mark.x` without registering the marker | Register the marker in `pytest.ini` / `pyproject.toml` to silence `PytestUnknownMarkWarning` and avoid CI failures on strict-marker projects |
| Editing plain `unittest.TestCase` code | `unittest` has no canonical trait attribute — emit a Markdown report instead |
