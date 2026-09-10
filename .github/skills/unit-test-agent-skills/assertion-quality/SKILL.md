---
name: assertion-quality
description: "Report assertion quality in existing tests. ALWAYS USE for weak, shallow, trivial, always-true, self-referential, assertion-free, presence/truthiness-only, or insufficiently diverse assertions. Supports .NET and Python. DO NOT USE for direct fixes: writing-mstest-tests owns supplied MSTest assertions; code-testing-agent owns new cases. Use test-gap-analysis for mutation reasoning and test-anti-patterns for general severity-ranked audits."
license: MIT
---

# Assertion Diversity Analysis

Analyze test code in .NET or Python to measure how varied and meaningful the assertions are. Produce a metrics report that reveals whether tests verify different facets of correctness — not just "output equals X" but also structure, exceptions, state transitions, side effects, and invariants.

> **Language-specific guidance**: Call the `test-analysis-extensions` skill to discover available extension files, then read the file matching the target codebase's language and framework (`dotnet.md` for .NET/MSTest/xUnit/NUnit/TUnit, `python.md` for pytest/unittest). You MUST read the relevant extension file before classifying assertions, because assertion APIs differ significantly across frameworks.

## Why Assertion Diversity Matters

Low assertion diversity signals shallow testing. Tests may pass while bugs hide in unasserted logic. Common symptoms:

| Problem | Symptom | Consequence |
|---------|---------|-------------|
| Trivial assertions | Test contains only `Assert.IsNotNull(result)` / `assert result is not None` / `expect(x).toBeDefined()` | Test passes but doesn't verify correctness |
| Single-value obsession | Always check one field or return value | Bugs in unasserted logic slip through |
| No negative assertions | Never check what shouldn't happen | Regressions sneak in through false positives |
| No state checks | Don't verify object state changes | Missed side-effects or lifecycle issues |
| No structural checks | Only assert top-level value | Bugs in nested objects go unnoticed |
| Assertion-free tests | Tests that call but don't verify | Code coverage lies; false security |

## When to Use

- User asks to evaluate assertion quality or depth
- User asks "are my tests actually testing anything meaningful?"
- User wants to know if test assertions are too shallow or trivial
- User asks for assertion coverage metrics or diversity analysis
- User suspects tests give false confidence despite passing
- The `code-testing-generator` agent (or any test-generation workflow) calls this skill as a pre-completion self-review step on freshly generated tests, before declaring the run finished

## When Not to Use

- User wants to write new tests (use `code-testing-agent` for any language, or `writing-mstest-tests` for MSTest specifically)
- User wants to detect anti-patterns beyond assertions (use `test-anti-patterns`)
- User wants to fix or rewrite assertions (help them directly)
- User asks about code coverage percentages (out of scope — this analyzes assertion quality, not line coverage)

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Test code | Yes | One or more test files or a test project directory to analyze |
| Production code | No | The code under test, to evaluate whether assertions cover the important behaviors |

## Workflow

### Step 1: Detect language and load extension

Identify the target codebase's language and test framework. Call the `test-analysis-extensions` skill and read the matching extension file (`extensions/dotnet.md` for .NET/MSTest/xUnit/NUnit/TUnit, `extensions/python.md` for pytest/unittest). If the codebase is not .NET or Python, decline the analysis and report that only .NET and Python are supported. The extension file lists the framework-specific assertion APIs you will classify in Step 3.

### Step 2: Gather the test code

Read all test files the user provides. If the user points to a directory or project, scan for all test files using the markers in the language extension file (e.g., `[TestMethod]` / `[Fact]` / `[Test]` for .NET, `def test_*` / `class Test*` for pytest/unittest).

### Step 3: Classify every assertion

For each test method, identify all assertions and classify them into these language-neutral categories:

| Category | What it verifies | Examples across languages |
|----------|------------------|----------------------------|
| **Equality** | Return value matches expected | `Assert.AreEqual` (MSTest), `Assert.Equal` (xUnit), `Is.EqualTo` (NUnit), `assert x == y` (pytest), `self.assertEqual` (unittest) |
| **Boolean** | Condition holds | `Assert.IsTrue`, `Assert.True`, `Is.True`, `assert flag` (pytest), `self.assertTrue` (unittest) |
| **Null / None** | Presence/absence of value | `Assert.IsNull` / `Assert.IsNotNull` (.NET), `assert x is None` / `assert x is not None` (pytest), `self.assertIsNone` (unittest) |
| **Exception / Error** | Error handling behavior | `Assert.ThrowsException<T>()` (MSTest), `Assert.Throws<T>()` (xUnit), `Assert.That(..., Throws.TypeOf<T>())` (NUnit), `pytest.raises(E)`, `self.assertRaises` (unittest) |
| **Type checks** | Runtime type correctness | `Assert.IsInstanceOfType`, `Is.InstanceOf<T>()`, `assert isinstance(x, T)`, `self.assertIsInstance` |
| **String** | Text content and format | `StringAssert.Contains`, `Does.Contain`, `assert sub in s`, `self.assertIn(sub, s)`, `re.search(pattern, s)` in a bare assert |
| **Collection** | Collection contents and structure | `CollectionAssert.Contains`, `Assert.Contains` (xUnit), `Has.Member` (NUnit), `assert item in collection`, `self.assertIn(item, coll)`, `self.assertCountEqual` |
| **Comparison** | Ordering and magnitude | `Assert.IsTrue(x > y)`, `Is.GreaterThan`, `assert x > y`, `self.assertGreater` |
| **Approximate** | Floating-point or tolerance-based | `Assert.AreEqual(expected, actual, delta)`, `Is.EqualTo(x).Within(delta)`, `pytest.approx(y)`, `self.assertAlmostEqual` |
| **Negative** | What should NOT happen | `Assert.AreNotEqual`, `Is.Not.EqualTo`, `assert x != y`, `self.assertNotEqual` |
| **State / Side-effect** | State transitions and side effects | Assertions on object properties after mutation; mock-call verifications: `mock.Verify(...)` (Moq), `Received()` (NSubstitute), `A.CallTo(...).MustHaveHappened()` (FakeItEasy), `mock_method.assert_called_with(...)` / `assert_called_once_with` (`unittest.mock`), `MagicMock().assert_awaited_with` (`pytest-asyncio`) |
| **Structural / Deep** | Deep object correctness | Rich-equality types with `Assert.AreEqual`, `Assert.Equivalent` (xUnit), fluent-assertions `Should().BeEquivalentTo`, `dict1 == dict2` deep compare in pytest, `syrupy` / snapshot fixtures |

A single assertion can belong to multiple categories (e.g., `Assert.AreNotEqual` is both Equality and Negative; `mock.Verify(m => m.Method(...))` is both State/Side-effect and a specific-call assertion).

Read the loaded language extension file for the exact framework-specific list of assertion APIs.

### Step 4: Compute metrics

Calculate these metrics for the test suite:

#### Per-test metrics
- **Assertion count**: Number of assertions in each test method
- **Assertion categories**: Which categories each test uses

#### Suite-wide metrics
- **Average assertions per test**: Total assertions / total test methods
- **Assertion type spread**: Number of distinct assertion categories used across the suite (out of 12)
- **Tests with zero assertions**: Count and percentage of test methods with no assertions at all
- **Tests with only trivial assertions**: Count and percentage of tests where every assertion is only a null check or `Assert.IsTrue(true)` — trivial means no meaningful value verification
- **Tests with self-referential assertions**: Count and percentage of tests whose assertions compare an input to a round-tripped or identity-transformed version of itself (e.g., `Assert.AreEqual(input, Parse(input.ToString()))`) or assert a field against itself (`Assert.AreEqual(dto.Name, dto.Name)`). These are tautological — they verify the plumbing, not the behavior.
- **Tests with negative assertions**: Count and percentage (target: at least 10% of tests should verify what should NOT happen)
- **Tests with exception assertions**: Count and percentage
- **Tests with state/side-effect assertions**: Count and percentage
- **Tests with structural/deep assertions**: Count and percentage
- **Single-category tests**: Count and percentage of tests that use only one assertion category

### Step 5: Apply calibration rules

Before reporting, calibrate findings:

- **Evaluate the matcher predicate before describing its weakness.** For every
  weak assertion, name one realistic defective value or behavior that would
  still satisfy that exact predicate. For every assertion credited as
  meaningful, name the behavior it pins. If you cannot give such a
  counterexample from the test and available production contract, do not
  speculate that the assertion is weak.
- **Trivial means truly trivial.** A null/None check alone is trivial (`Assert.IsNotNull(result)`, `assert result is not None`). But a null check followed by a meaningful value assertion is not trivial — the null check is a guard before the real assertion. Only flag a test as "trivial" if it has no meaningful value assertions.
- **Boolean assertions checking meaningful conditions are not trivial.** `Assert.IsTrue(result.IsValid)` / `assert result.is_valid` check a specific property — these are Boolean assertions, not trivial ones. Always-true assertions (`Assert.IsTrue(true)`, `assert True`) are trivial.
- **Consider the test's intent.** A test for a void method that verifies state change on a dependency is legitimate even if it only uses one Boolean assertion.
- **Exception tests are inherently low-assertion-count.** `Assert.ThrowsException<T>(() => ...)` / `with pytest.raises(E): ...` may be the only assertion — that's fine for exception-focused tests. Don't penalize them for low assertion count.
- **Mock-call verifications and bare assertion forms count.** Treat `mock.Verify(...)` (Moq), `Received()` (NSubstitute), `mock.assert_called_with(...)` (unittest.mock), and bare `assert` (pytest) all as real assertions of the appropriate category. Do not treat them as missing-framework-API smells.
- **Snapshot assertions** (`syrupy` in pytest, verified-file snapshot libraries in .NET) count as Structural/Deep assertions. Flag stale or never-updated snapshots separately.
- **Property-based tests** (`@given` Hypothesis in pytest, `FsCheck` / property tests in .NET) generate assertions implicitly through generated cases — count the inner assertion logic, not the outer scaffold.
- **Don't conflate diversity with volume.** A test with 20 equality assertions has high volume but low diversity. A test with one equality, one null check, and one exception assertion has low volume but good diversity.
- **Self-referential assertions are not meaningful equality checks.** Asserting that an output equals an input round-trip looks like a real equality assertion but is tautological when the operation under test is expected to be identity. Flag these separately from normal equality assertions. If the test's *purpose* is to verify a round-trip (serialize/deserialize, encode/decode), the assertion is valid — but it should be accompanied by assertions on non-trivial inputs that exercise the transformation.
- **If assertions are well-diversified, say so.** A report concluding the suite has good diversity is perfectly valid.

### Step 6: Report findings

**Scale the report depth to the size and complexity of the suite.** The structure below is the full template for a substantial suite (roughly 15+ tests or a multi-file project). For a small or simple input (a single file with only a handful of tests), do not emit every section — a padded multi-section dashboard on a trivial input reads as noise and buries the answer. Instead, answer the user's question directly and concisely: which tests are assertion-free or trivial-only, the overall assertion-quality verdict, and concrete recommendations (still distinguishing intentional smoke tests from tests masquerading as real verification). Use only the sections that carry real signal for the input at hand; a short metric summary plus the assertion-free list and recommendations is often enough. Never omit the rubric-relevant substance (assertion-free/trivial identification, the quality verdict, and concrete recommendations) — only trim structural overhead that adds no information.

For a five-to-eight-test file, default to one verdict plus one compact per-test
table. Omit category-spread dashboards and hypothetical failure modes unless the
caller asks for metrics. State only counterexamples supported by the assertion
predicate and available production behavior.

Present the analysis in this structure:

1. **Summary Dashboard** — A quick-reference table of key metrics:
   ```
   | Metric                        | Value  | Assessment |
   |-------------------------------|--------|------------|
   | Total tests                   | 25     | —          |
   | Average assertions per test   | 2.4    | Moderate   |
   | Assertion type spread         | 5/12   | Low        |
   | Tests with zero assertions    | 3 (12%)| Concerning |
   | Tests with only trivial asserts | 4 (16%)| Acceptable |
   | Tests with negative assertions | 2 (8%) | Below target |
   | Single-category tests         | 15 (60%)| High       |
   ```

2. **Category Breakdown** — For each assertion category, show:
   - How many tests use it
   - Representative examples from the code
   - Whether it's overused or underused relative to the code under test

3. **Gap Analysis** — Based on the production code (if available), identify:
   - Behaviors that are tested but only with equality checks
   - Error paths with no exception assertions
   - State-changing methods with no state verification
   - Collections returned but never checked for contents

4. **Recommendations** — Prioritized list of improvements:
   - Which tests would benefit most from additional assertion types
   - Which assertion categories are missing and why they matter
   - Concrete examples of assertions that could be added

5. **Assertion-free tests** — If any exist, list each one with its method name and what it appears to be testing, so the user can decide whether to add assertions or mark them as intentional smoke tests.

## Validation

- [ ] Every assertion in the test suite was classified into at least one category
- [ ] Metrics are computed correctly (counts add up)
- [ ] Trivial-assertion tests are correctly identified (not over-flagged)
- [ ] Exception tests are not penalized for low assertion count
- [ ] Boolean assertions on meaningful properties are not classified as trivial
- [ ] Every weak-assertion claim includes a realistic counterexample that the
      exact matcher would accept
- [ ] Recommendations are concrete (name specific test methods and suggest specific assertion types)
- [ ] If the suite has good diversity, the report acknowledges this

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Penalizing exception tests for low assertion count | Exception assertions are complete on their own — skip count warnings for these |
| Flagging null/None checks before value checks as trivial | Only flag tests where the null/None check is the ONLY assertion |
| Counting any Boolean assertion as trivial | Only always-true assertions (`Assert.IsTrue(true)`, `assert True`) are trivial |
| Ignoring framework differences | Each framework has distinct assertion APIs — always read the matching language extension first. MSTest's `Assert.AreEqual`, xUnit's `Assert.Equal`, NUnit's `Is.EqualTo`, pytest's bare `assert ==`, and unittest's `self.assertEqual` all map to the **Equality** category |
| Treating bare assertion forms as missing-framework | Bare `assert` in pytest is canonical — count it in the right category |
| Treating mock-call verifications as assertion-free | `mock.Verify(...)`, `Received()`, `mock.assert_called_with(...)` are State/Side-effect assertions |
| Recommending diversity for diversity's sake | Only suggest adding assertion types that would catch real bugs in the code under test |
| Missing implicit assertions | Exception assertions are both Exception and Negative; snapshot/property-based tests are real assertions with implicit structure |
| Async tests with unawaited assertions | xUnit `async Task` tests calling `Assert.ThrowsAsync` without `await`, and pytest-asyncio tests with un-awaited coroutines, silently pass even when the underlying assertion would have failed — treat as assertion-free even when assertion calls are present |
