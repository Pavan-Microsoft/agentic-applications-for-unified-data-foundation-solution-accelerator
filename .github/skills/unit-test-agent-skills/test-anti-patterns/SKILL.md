---
name: test-anti-patterns
description: >
  Audit a test file or suite; produce a severity-ranked diagnostic report.
  ALWAYS USE for tests that verify nothing, missing/tautological
  assertions, swallowed/broad exceptions, flaky/order-dependent tests,
  duplication, or magic values. Supports .NET (MSTest/xUnit/NUnit/TUnit)
  and Python (pytest/unittest). DO NOT USE for direct edits:
  writing-mstest-tests owns supplied MSTest assertions/attributes/lifecycle;
  code-testing-agent owns new tests. Exclude running tests, migration, assertion
  metrics (assertion-quality), raw .NET coverage collection (run-tests),
  non-.NET coverage collection/analysis (native tooling), project-wide .NET coverage/CRAP
  (coverage-analysis), named-target .NET CRAP
  (crap-score), behavioral/pseudo-mutation gaps (test-gap-analysis), test-mix/
  happy-vs-error classification and trait distributions (test-tagging), or the
  testsmells.org catalog (test-smell-detection).
license: MIT
---

# Test Anti-Pattern Detection

Quick, pragmatic analysis of test code in .NET (MSTest/xUnit/NUnit/TUnit) and Python (pytest/unittest) for anti-patterns and quality issues that undermine test reliability, maintainability, and diagnostic value.

> **Language-specific guidance**: Call the `test-analysis-extensions` skill to discover available extension files, then read the file matching the target codebase (`extensions/dotnet.md` for .NET, `extensions/python.md` for pytest/unittest). The extension file tells you which sleep / time / random / skip / setup-teardown / mystery-guest APIs to look for in that language. If the codebase is not .NET or Python, decline the audit and report that only .NET and Python are supported.

## When to Use

- User asks to review test quality or find test smells
- User wants to know why tests are flaky or unreliable
- User asks "are my tests good?" or "what's wrong with my tests?"
- User requests a test audit or test code review
- User wants diagnostic findings before deciding what to improve

## When Not to Use

- User wants to write new tests from scratch (use `code-testing-agent`)
- User wants direct implementation fixes rather than a diagnostic review (use the relevant write/edit skill)
- User asks to fix swapped `Assert.AreEqual` argument order in MSTest (use `writing-mstest-tests`)
- User asks to convert MSTest `DynamicData` from `IEnumerable<object[]>` to `ValueTuple` (use `writing-mstest-tests`)
- User wants to run or execute tests (use `run-tests` for .NET)
- User wants to migrate between test frameworks or versions (use migration skills)
- User wants raw .NET coverage collection (use `run-tests`), non-.NET coverage collection or analysis (use native tooling), project-wide .NET coverage/CRAP metrics (use `coverage-analysis`), or named-target .NET CRAP (use `crap-score`)
- User asks whether tests would catch a bug or wants behavioral/pseudo-mutation gaps (use `test-gap-analysis`)
- User wants test-mix or happy-vs-error-path classification, standardized tagging, or trait/category distributions (use `test-tagging`)
- User wants a deep formal test smell audit with academic taxonomy and extended catalog (use `test-smell-detection`)

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Test code | Yes | One or more test files or classes to analyze |
| Production code | No | The code under test, for context on what tests should verify |
| Specific concern | No | A focused area like "flakiness" or "naming" to narrow the review |

## Workflow

### Step 1: Detect language and load extension

Identify the target codebase's language and test framework. Call the `test-analysis-extensions` skill and read the matching extension file. The extension file documents framework-specific anti-pattern markers — what counts as a sleep/wait, a test marker, a skip, a setup/teardown, a shared-state hot spot, and an integration boundary — so this skill stays language-neutral.

### Step 2: Gather the test code

Read the test files the user wants reviewed. If the user points to a directory or project, scan for all test files using the discovery markers in the loaded language extension file (`[TestClass]`/`[TestMethod]` / `[Fact]` / `[Theory]` / `[Test]` for .NET; `test_*.py` / `def test_*` / `class Test*` for pytest and unittest).

If production code is available, read it too -- this is critical for detecting tests that are coupled to implementation details rather than behavior.

### Step 3: Scan for anti-patterns

Check each test file against the anti-pattern catalog below. Report findings grouped by severity. The examples cover .NET and Python — use the loaded language extension file to map each pattern to the exact framework you are auditing.

#### Critical -- Tests that give false confidence

| Anti-Pattern | What to Look For |
|---|---|
| **No assertions** | Test methods that execute code but never assert anything. A passing test without assertions proves nothing. In .NET look for missing `Assert.*`; in pytest a function with no `assert` and no `pytest.raises`; in unittest a method with no `self.assert*`. Mock-call verifications (`Verify(...)` (Moq), `Received()` (NSubstitute), `mock.assert_called_with(...)` (unittest.mock)) are real assertions. |
| **Missing await on async assertions** | .NET: async `Task` xUnit/MSTest test calling `Assert.ThrowsAsync` without `await`. Python: `pytest-asyncio` test with an un-awaited coroutine, or `AsyncMock.assert_awaited*` on a coroutine that was never awaited. These tests silently pass even when the underlying assertion would have failed. |
| **Coverage touching** | Test class that methodically calls every public member on a type — often in alphabetical or declaration order — without asserting meaningful outcomes. Each test typically does `var result = sut.MethodName(...)` (or `result = sut.method_name(...)`) with no assertion, or only a trivial null/None check. The intent is to inflate code-coverage metrics rather than verify behavior. Distinct from a single assertion-free test: the pattern is *systematic* coverage of the surface area with no real verification. |
| **Self-referential assertion** | The expected value is computed from the same actual value, such as `Assert.AreEqual(dto.Name, dto.Name)`, `Assert.AreEqual(result, result)`, `assert result == result`, or equivalents. Do not apply this label merely because a valid identity, clone, serialization, or round-trip contract compares output with input: those assertions can fail. Instead check whether the input exercises a transformation and whether independently known representation, field, reference-identity, or invalid-input assertions are missing. |
| **Swallowed exceptions** | `try { ... } catch { }`, `catch (Exception)` without rethrowing or asserting (.NET); bare `except:` or `except Exception:` with `pass` (Python). |
| **Assert in catch block only** | `try { Act(); } catch (Exception ex) { Assert.Fail(ex.Message); }` (.NET) or `try: act(); except Exception as e: pytest.fail(str(e))` (Python) — use `Assert.ThrowsException` / `pytest.raises` / `self.assertRaises` instead. The test passes when no exception is thrown even if the result is wrong. |
| **Always-true assertions** | `Assert.IsTrue(true)`, `Assert.AreEqual(x, x)`, `assert True`, or conditions that can never fail. |
| **Commented-out assertions** | Assertions that were disabled but the test still runs, giving the illusion of coverage. |

#### High -- Tests likely to cause pain

| Anti-Pattern | What to Look For |
|---|---|
| **Flakiness indicators** | Wall-clock sleeps/waits used for synchronization: `Thread.Sleep` / `Task.Delay` (.NET), `time.sleep` / `asyncio.sleep` (Python). Wall-clock reads without abstraction: `DateTime.Now` / `DateTime.UtcNow` (.NET), `datetime.now()` / `datetime.utcnow()` / `time.time()` (Python). Unseeded randomness: `new Random()` (.NET), `random.random()` / `random.randint()` (Python). Environment-dependent paths (hard-coded `C:\...`, `/tmp/...`, network hosts). |
| **Test ordering dependency** | Static/global mutable state modified across tests; setup that doesn't fully reset state (`[TestInitialize]` / `[ClassInitialize]` in .NET, `setUp` / `setUpClass` / `@pytest.fixture` in Python); tests that fail when run individually but pass in suite (or vice versa). Examples per language: `static` fields (.NET), module-level globals (Python), class-level attributes in unittest without proper reset. |
| **Over-mocking** | More mock setup lines than actual test logic. Verifying exact call sequences on mocks rather than outcomes. Mocking types the test owns. Per language: Moq / NSubstitute / FakeItEasy (.NET); `unittest.mock` / `pytest-mock` (Python). For a deep mock audit in .NET, use `exp-mock-usage-analysis`. |
| **Implementation coupling** | Testing private methods via reflection (`MethodInfo.Invoke` in .NET, `getattr` on a private-by-convention `_name` in Python). Asserting on internal state instead of observable behavior. Verifying exact method call counts on collaborators instead of business outcomes. |
| **Broad exception assertions** | `Assert.ThrowsException<Exception>(...)` (.NET) / `pytest.raises(Exception)` / `self.assertRaises(Exception)` (unittest) without checking the message or exact type. |

#### Medium -- Maintainability and clarity issues

| Anti-Pattern | What to Look For |
|---|---|
| **Poor naming** | Test names like `Test1`, `TestMethod`, `test`, names that don't describe the scenario or expected outcome. Good naming differs by language convention — see the loaded language extension file (e.g., `Add_NegativeNumber_ThrowsArgumentException` for .NET, `test_add_negative_number_raises_value_error` for pytest). |
| **Magic values** | Unexplained numbers or strings in arrange/assert: `Assert.AreEqual(42, result)` / `assert result == 42` — what does 42 mean? |
| **Duplicate tests** | Three or more test methods with near-identical bodies that differ only in a single input value. Should be parametrized: `[DataRow]` / `[DataTestMethod]` (MSTest), `[Theory]` + `[InlineData]` / `[MemberData]` (xUnit), `[TestCase]` (NUnit), `@pytest.mark.parametrize` (pytest). For a detailed duplication analysis in .NET, use `exp-test-maintainability`. Note: Two tests covering distinct boundary conditions (e.g., zero vs. negative) are NOT duplicates — separate tests for different edge cases provide clearer failure diagnostics and are a valid practice. |
| **Giant tests** | Test methods exceeding ~30 lines or testing multiple behaviors at once. Hard to diagnose when they fail. |
| **Assertion messages that repeat the assertion** | `Assert.AreEqual(expected, actual, "Expected and actual are not equal")` (.NET) / `assert x == y, "x is not equal to y"` (pytest) add no information. Messages should describe the business meaning. |
| **Missing AAA / Given-When-Then separation** | Arrange/Act/Assert (or Given/When/Then) phases are interleaved or indistinguishable. |

#### Low -- Style and hygiene

| Anti-Pattern | What to Look For |
|---|---|
| **Unused test infrastructure** | Setup/teardown hooks that do nothing — `[TestInitialize]` / `[TestCleanup]` / `[ClassInitialize]` in .NET, `setUp` / `tearDown` / `@pytest.fixture` in Python — and test helper methods that are never called. |
| **Unmanaged resources** | Test creates disposable/closeable resources without cleanup: `HttpClient` / `Stream` without `using` (.NET); file/connection without `with` block or `try/finally` (Python); missing teardown for temp files or in-memory databases in either language. |
| **Print debugging** | Leftover `Console.WriteLine` / `Debug.WriteLine` (.NET) or `print(...)` (Python) statements used during test development. |
| **Inconsistent naming convention** | Mix of naming styles in the same test class/module/file (e.g., some use `Method_Scenario_Expected`, others use `ShouldDoSomething` or `test_should_do_something`). |

### Step 4: Calibrate severity honestly

Before reporting, re-check each finding against these severity rules:

- **Critical/High**: Only for issues that cause tests to give false confidence or be unreliable. A test that always passes regardless of correctness is Critical. Flaky shared state is High. Missing-await on async assertions is Critical (silent pass).
- **Medium**: Only for issues that actively harm maintainability -- 5+ nearly-identical tests, truly meaningless names like `Test1` / `test` / `it1`.
- **Low**: Cosmetic naming mismatches, minor style preferences, assertion messages that could be better. When in doubt, rate Low.
- **Use the caller's severity vocabulary consistently.** If the caller asks for
  Critical / Warning / Info, map reliability risks to Warning and
  maintenance/cosmetic concerns to Info rather than silently collapsing every
  item into Critical. Severity describes the demonstrated failure mode, not how
  much prose a finding receives.
- **Separate a systemic finding from its instances.** Coverage touching across a
  facade is one Critical systemic finding whose evidence lists every affected
  test. All assertion-free instances, including the last facade method, retain
  the same false-confidence severity. Report `1 finding / 6 affected tests`, not
  six findings plus a seventh summary finding, and do not downgrade one instance
  merely to manufacture multiple tiers.
- **Do not severity-rank ordinary missing cases as anti-patterns.** Adjacent
  untested branches, exception paths, and boundaries may be useful coverage
  opportunities, but list them separately from the anti-pattern counts unless a
  weak existing test specifically creates the gap. They are not Critical merely
  because the suite has a systemic Critical issue.
- **Not an issue** (per-language nuance):
  - pytest **bare `assert`** is the canonical assertion form, not a missing assertion library. Do NOT flag.
  - pytest `@pytest.mark.parametrize` and .NET data-driven attributes (`[DataRow]`, `[Theory]` + `[InlineData]`, `[TestCase]`) are idiomatic, not "Conditional Test Logic". Do NOT flag their iteration loops.
  - Separate tests for distinct boundary conditions (zero vs. negative vs. null). Do NOT flag as duplicates.
  - Explicit per-test setup instead of `[TestInitialize]` / pytest fixtures (this *improves* isolation).
  - Tests that are short and clear but could theoretically be consolidated.
  - Round-trip or serialization equality with non-trivial input. It is valid
    metamorphic evidence; suggest an independent representation assertion when
    two implementations could share the same bug.
  - Clone value equality. Keep it, and add distinct-reference or mutation-
    independence evidence when the contract promises a deep copy.
  - A validator or accessor returning the original value when pass-through is the
    production contract. Missing invalid-input cases are a coverage gap, not proof
    that the existing assertion is tautological.

IMPORTANT: If the tests are well-written, say so clearly up front. Do not inflate severity to justify the review. A review that finds zero Critical/High issues and only minor Low suggestions is a valid and valuable outcome. Lead with what the tests do well.

### Step 5: Report findings

**Depth bar — a tidy report that is shallower than an unassisted review is a failure.** Before writing, satisfy all five:

1. **Account for every test in scope.** Build the complete method/field inventory
   before summarizing. For a systematic pattern such as coverage touching,
   enumerate every affected test at least once rather than giving representative
   examples. A finding table that silently skips tests (or fixtures like an
   unused `static HttpClient` field) is incomplete. State the number reviewed.
2. **Verify the production contract before judging the oracle.** Inspect the
   actual transformation, DTO fields, and promised identity/clone semantics.
   Never invent fields or require lossless round-tripping when production is
   intentionally lossy.
3. **Make every Critical/High fix complete and specific.** Give the replacement assertion with the *exact expected value* (the computed discount, the exact CSV line, the full expected object), not a `// assert something here` placeholder.
4. **Name the adjacent gaps the tests should also cover** — untested error paths, boundary values, and round-trip/culture-sensitivity risks in the same class. These are part of "what's wrong with my tests", and omitting them is the most common way this review loses to an unassisted one.
5. **Keep the report internally consistent.** Summary counts must equal the enumerated findings. Publish a settled conclusion: do all reconsidering before you write, and never leave "wait, that's wrong" / "this should fail but doesn't" reasoning in the output.

Present findings in this structure:

1. **Summary** -- Total issues found, broken down by severity (Critical / High / Medium / Low). If tests are well-written, lead with that assessment.
2. **Critical and High findings** -- List each with:
   - The anti-pattern name
   - The specific location (file, method name, line)
   - A brief explanation of why it's a problem
   - A concrete fix (show before/after code when helpful)
3. **Medium and Low findings** -- Summarize in a table unless the user wants full detail
4. **Positive observations** -- Call out things the tests do well (sealed class, specific exception types, data-driven tests, clear AAA structure, proper use of fakes, good naming). Don't only report negatives.

Before publishing, assign each finding a stable identity. A grouped row counts
as one finding regardless of how many methods it lists; separate rows count
separately. Recompute the summary from those rows. Keep `affected tests` as a
different number so a bundled finding cannot create a hidden count mismatch.

### Step 6: Prioritize recommendations

If there are many findings, recommend which to fix first:

1. **Critical** -- Fix immediately, these tests may be giving false confidence
2. **High** -- Fix soon, these cause flakiness or maintenance burden
3. **Medium/Low** -- Fix opportunistically during related edits

## Validation

- [ ] Every test method in scope is accounted for (reviewed count stated; none silently skipped)
- [ ] Identity and round-trip findings match the production contract and use only real fields
- [ ] Every finding includes a specific location (not just a general warning)
- [ ] Every Critical/High finding includes a concrete fix with exact expected values
- [ ] Adjacent untested error paths and boundary values are called out
- [ ] Summary counts match the enumerated findings
- [ ] Grouped findings distinguish finding count from affected-test count
- [ ] Adjacent coverage opportunities are not inflated into Critical anti-pattern findings
- [ ] Report covers all categories (assertions, isolation, naming, structure)
- [ ] Positive observations are included alongside problems
- [ ] Recommendations are prioritized by severity

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Reporting style issues as critical | Naming and formatting are Medium/Low, never Critical |
| Suggesting rewrites instead of targeted fixes | Show minimal diffs -- change the assertion, not the whole test |
| Flagging intentional design choices | If `Thread.Sleep` / `time.sleep` is in an integration test testing actual timing, that's not an anti-pattern. Consider context. |
| Inventing false positives on clean code | If tests follow best practices, say so. A review finding "0 Critical, 0 High, 1 Low" is perfectly valid. Don't inflate findings to justify the review. |
| Flagging separate boundary tests as duplicates | Two tests for zero and negative inputs test different edge cases. Only flag as duplicates when 3+ tests have truly identical bodies differing by a single value. |
| Rating cosmetic issues as Medium | Naming mismatches (e.g., method name says `ArgumentException` but asserts `ArgumentOutOfRangeException`) are Low, not Medium -- the test still works correctly. |
| Ignoring the test framework | Use the terminology of the framework you loaded from the language extension; don't describe a pytest suite in MSTest terms. |
| Missing the forest for the trees | If 80% of tests have no assertions, lead with that systemic issue rather than listing every instance |
| Trading depth for tidiness | A severity table and positive observations do not substitute for coverage of every test, exact expected values in fixes, and the adjacent error-path/boundary gaps |
| Contradicting yourself in the report | Reason first, then write one settled verdict per finding — never emit "wait, that's wrong" / "should fail but doesn't" reconsiderations |
| Counts that don't add up | The summary's per-severity totals must match the findings you listed |
