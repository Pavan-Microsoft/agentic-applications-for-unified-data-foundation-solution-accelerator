# Unit Test Writer Agent

`unit-test-writer` generates unit tests for any file or module in a repository by delegating to
the in-repo `code-testing-generator` pipeline. It is polyglot and works with Python, TypeScript,
JavaScript, C#, Go, Java, Rust, and any other language present in the workspace.

The agent never writes test code itself. It routes every request through a Research, Plan,
Implement pipeline that detects the language, discovers existing test conventions, writes the
tests, runs them, and fixes failures until the suite is green.

## Required files

The agent is useless on its own because it delegates. Copy the whole set below into any repo that
should have it, preserving the paths.

| Path | Purpose |
|---|---|
| `.github/agents/unit-test-writer.agent.md` | User-facing entry point |
| `.github/agents/code-testing-generator.agent.md` | Pipeline orchestrator |
| `.github/agents/code-testing-researcher.agent.md` | Discovers structure, frameworks, conventions |
| `.github/agents/code-testing-planner.agent.md` | Produces the phased test plan |
| `.github/agents/code-testing-implementer.agent.md` | Writes the test files |
| `.github/agents/code-testing-builder.agent.md` | Runs build and compile steps |
| `.github/agents/code-testing-tester.agent.md` | Runs the test suite |
| `.github/agents/code-testing-fixer.agent.md` | Repairs compilation and import failures |
| `.github/agents/code-testing-linter.agent.md` | Applies formatting and lint fixes |
| `.github/skills/code-testing-agent/` | Default conventions, coverage goals, quality bar |
| `.github/skills/code-testing-extensions/` | Language-specific authoring guidance |

These skills are optional but improve the quality gate the pipeline applies before reporting
completion: `assertion-quality`, `test-gap-analysis`, `test-anti-patterns`, `find-untested-sources`,
`coverage-analysis`, `run-tests`.

## Prerequisites

### Editor

Use VS Code with GitHub Copilot Chat in agent mode. Agent definitions under `.github/agents/` are
discovered automatically. If a newly added agent does not appear in the picker, reload the window.

### Language toolchain

The pipeline runs the tests it writes, so the runner and its dependencies must be installed and
importable before you invoke the agent. Install the stack that matches the code under test.

#### Python

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Windows PowerShell
# source .venv/bin/activate       # macOS or Linux

python -m pip install --upgrade pip
python -m pip install -r path/to/requirements.txt
python -m pip install pytest pytest-asyncio pytest-cov
```

Install the production dependencies as well, not only the test tooling. The generated tests import
the module under test, so every third-party package that module imports has to resolve. Web
frameworks add one more requirement: `fastapi.testclient.TestClient` and Starlette's test client
both need `httpx`, which is frequently present only as a transitive dependency. Pin it explicitly
if your suite drives HTTP routes.

Pin the test tooling in the same `requirements.txt` that CI installs. A local environment that
drifts from the pinned versions can pass while CI fails, and `pytest-asyncio` in particular
changed fixture and event-loop behavior across major versions.

#### .NET

```powershell
dotnet restore
dotnet tool install --global dotnet-reportgenerator-globaltool   # optional, for coverage reports
```

#### Node, TypeScript, and JavaScript

```powershell
npm ci
npm install --save-dev jest @types/jest ts-jest    # or vitest
```

#### Go

```powershell
go mod download
```

#### Java

```powershell
mvn -q dependency:resolve       # or: ./gradlew dependencies
```

#### Rust

```powershell
cargo fetch
cargo install cargo-llvm-cov    # optional, for coverage
```

## Setup instructions

Work through these steps once per repository. Steps 4 and 5 matter more than they look: the
pipeline runs the tests it writes, so a runner that cannot execute today will send the agent into a
repair loop against a problem it did not create.

1. Copy the agent and skill files from the required files table into the target repo, preserving the
   `.github/agents/` and `.github/skills/` paths.
2. Reload the VS Code window.
3. Open Copilot Chat and confirm `unit-test-writer` appears in the agent picker.
4. Create and activate the environment for the language under test, then install both the production
   dependencies and the test tooling.
5. Run the existing test suite once. A green baseline, or a knowingly empty one, is the signal that
   the toolchain is ready.
6. Confirm the coverage tool produces a report, using the command for your stack from the verifying
   section below.
7. Add `.testagent/` to `.gitignore` so the pipeline's working notes stay out of commits.

```powershell
# Example: Python, from the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r path/to/requirements.txt
python -m pip install pytest pytest-asyncio pytest-cov
python -m pytest --collect-only -q          # step 5: does the runner work at all
```

## Recommended model

Pick the model in Copilot Chat before starting the run. Sub-agents inherit the model from the
parent invocation, and switching partway through means restarting, so choose deliberately.

| Request shape | Suggested model tier | Why |
|---|---|---|
| One function or one small class | Mid tier, such as a Sonnet or GPT-5 mini class option | The pipeline takes the Direct strategy, writes tests immediately, and needs little planning |
| One file or one module | Frontier reasoning model | Branch enumeration and mock design drive quality here |
| A package, or an explicit coverage target | Frontier reasoning model, for example Claude Opus 5 | The Iterative strategy re-plans against coverage gaps across many turns |
| Async, concurrency, or heavy mocking | Frontier reasoning model | Fake async iterators, event loops, and context managers are where weaker models produce tests that pass without asserting anything |

Available models vary by Copilot plan and change over time, so treat the names as examples and pick
the strongest reasoning option your picker offers for anything beyond a single function.

A smaller model is a reasonable choice when you are regenerating a suite you already reviewed, or
when the target is pure logic with no I/O.

## How to trigger

### From the agent picker

Open Copilot Chat, choose `unit-test-writer` from the agent dropdown, then describe the target.

### From the default agent

Ask for the agent by name and the request is routed for you.

```text
Use the unit-test-writer agent to generate unit tests for src/services/billing.py
```

### Prompt template

The agent asks for clarification when the target is missing, so state it up front. Fill in the
placeholders and paste the whole block.

```text
Generate unit tests for <path/to/file>.

Scope:
- Test only <file or module>. Do not modify production code.
- Create the tests in <target folder>.
- Ignore <folders to skip, for example existing e2e or integration suites>.

Requirements:
- Framework: <pytest | xUnit | Jest | JUnit | go test | cargo test>
- Mock every external dependency: <databases, HTTP clients, cloud SDKs, clocks>
- Coverage target: more than <N>% line coverage of <file>

Verification:
- Run the suite and produce a coverage report.
- Inspect the uncovered lines and add tests until the target is met and every test passes.

Report back: the test plan, prerequisites, exact run commands, final pass/fail counts,
the final coverage percentage, and the path of every file created.
```

### Request checklist

Vague requests produce sprawling suites, so constrain them. Name the exact target, the folder that
should receive the new tests, any directory the agent must not touch, the framework and mocking
library, a numeric coverage target, which collaborators must be mocked, and whether production code
may be edited.

## Demo instructions

A five minute walkthrough that shows the agent end to end. Choose a module with real branching and
at least one external dependency to mock, because a trivial pure function hides everything
interesting about the pipeline.

1. Pick the target and confirm it currently has no tests, or few.

   ```powershell
   python -m pytest --cov=<module> --cov-report=term-missing -q
   ```

   Record the starting percentage. Zero is a fine starting point and makes the demo clearer.

2. Open Copilot Chat, select `unit-test-writer`, and paste a filled-in prompt template.

   ```text
   Generate unit tests for src/services/billing.py.

   Scope:
   - Test only billing.py. Do not modify production code.
   - Create the tests in src/services/.
   - Ignore the existing e2e suite.

   Requirements:
   - Framework: pytest
   - Mock every external dependency: the database client and the HTTP payment gateway
   - Coverage target: more than 85% line coverage of billing.py

   Verification:
   - Run the suite and produce a coverage report.
   - Inspect the uncovered lines and add tests until the target is met and every test passes.

   Report back: the test plan, prerequisites, exact run commands, final pass/fail counts,
   the final coverage percentage, and the path of every file created.
   ```

3. Watch the pipeline announce its stages. Research and planning come first on anything larger than
   a single function, then implementation, then a build, test, and fix loop.

4. Re-run coverage yourself rather than trusting the summary.

   ```powershell
   python -m pytest <new test file> --cov=<module> --cov-report=term-missing
   ```

5. Show that production code was untouched.

   ```powershell
   git status --short
   git diff -- <path to the module under test>
   ```

   An empty diff for the module and a pair of untracked test files is the result you want.

6. Open one generated test and read it aloud. Point out the mocked boundary and the specific values
   being asserted. This is the part of the demo that earns trust.

7. Reset if you were only demonstrating.

   ```powershell
   git clean -n <target folder>    # preview first
   ```

## Verifying the result

Run the suite yourself after the agent reports success.

| Stack | Command |
|---|---|
| Python | `python -m pytest <test path> --cov=<module> --cov-report=term-missing` |
| .NET | `dotnet test --collect:"XPlat Code Coverage"` |
| Node or TypeScript | `npx jest --coverage` or `npx vitest run --coverage` |
| Go | `go test ./... -coverprofile=coverage.out && go tool cover -func=coverage.out` |
| Java | `mvn test jacoco:report` or `./gradlew test jacocoTestReport` |
| Rust | `cargo llvm-cov --summary-only` |

> [!TIP]
> For Python, pass an importable module or package name to `--cov`, not a file path.
> `--cov=src/api/history.py` emits a `module-not-imported` warning and reports no data.
> Use `--cov=history` when the module is on `sys.path`, or `--cov=src/api` to scope by directory.

## Folder structure guidance

The pipeline reads existing conventions before it writes anything. When the repo already has tests,
new tests land beside them in the established layout, and existing files are extended rather than
duplicated. When no convention exists, it falls back to the ecosystem default.

| Language | Default location | Naming |
|---|---|---|
| Python | Alongside the module, or a sibling `tests/` package | `test_<module>.py` |
| .NET | A separate `<Project>.Tests` project | `<Class>Tests.cs` |
| Node or TypeScript | `__tests__/`, or beside the source | `<module>.test.ts` or `<module>.spec.ts` |
| Go | Same package directory | `<file>_test.go` |
| Java | `src/test/java/` mirroring the main package tree | `<Class>Test.java` |
| Rust | `#[cfg(test)]` in the same file, or `tests/` for integration | `mod tests` or `<feature>.rs` |

The pipeline also writes working notes to a `.testagent/` directory at the repo root.

```text
.testagent/
  research.md      # structure, frameworks, and conventions discovered
  plan.md          # the phased implementation plan
  research-2.md    # later iterations, when the Iterative strategy runs
  plan-2.md
```

These are scratch artifacts, not deliverables. Keep them out of commits with a `.gitignore` entry,
and read them when you want to understand why the agent made a particular choice.

Two habits save rework. State the destination folder explicitly in the request, because inference
is good but not free. And avoid giving a new test file the same basename as one that already exists
elsewhere in the repo, since pytest cannot collect two same-named modules when neither directory has
an `__init__.py`.

## Guardrails

Review what the pipeline produces before merging. Generated tests pin the behavior the code has
today, which is not always the behavior the code was meant to have. A route that swallows a 404
inside a broad `except` and returns 500 gets a test asserting 500. That is an accurate test and a
useful signal, but treat it as a finding rather than a specification.

Confirm the agent left production code alone unless you asked otherwise, and check that assertions
verify real values rather than truthiness. Ask for a `git diff` if you are unsure what changed.

## Known limitations and issues

The agent cannot function alone. It delegates every request and fails immediately if any
`code-testing-*` sub-agent is missing, which is the usual outcome of copying only the entry point
into a new repo.

It will not provision your environment. Missing packages surface as generated tests that fail to
import, and the fix loop cannot install what the repo never declared.

Generated tests describe behavior as it exists, bugs included. A handler that swallows an exception
and returns the wrong status code gets a test asserting the wrong status code. Read the output as
evidence of what the code does, then decide separately whether that is what it should do.

Coverage targets are not always reachable. Code that calls a clock, the filesystem, or the network
directly, with no injectable seam, blocks certain branches entirely. Reaching the target there
requires a production change, which the agent will not make unless you ask for one.

Runs are not deterministic. Two invocations against the same file produce different test counts,
names, and structure. Regenerating is not a way to reproduce a previous result.

Large scopes strain the context window. A package-wide request may need several invocations with
narrowed focus rather than one sweeping prompt.

Mocks sometimes over-specify. Assertions on internal call ordering or private collaborators create
tests that break on harmless refactors, so prune them during review.

VS Code registers every markdown file in `.github/agents/` as an agent. This README currently
appears in the agent picker as `unit-test-writer.README` with no description. It is harmless but
untidy, and moving the file out of that folder resolves it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent missing from the picker | Definition not discovered | Confirm the file sits at `.github/agents/unit-test-writer.agent.md`, then reload the window |
| Agent replies without producing tests | Delegation returned empty | Re-ask with an explicit file path; the agent is required to retry rather than write tests itself |
| Delegation fails immediately | Sub-agent files missing | Copy the full `code-testing-*` set from the required files table |
| `ModuleNotFoundError` in generated tests | Module directory not on the import path | Add a `conftest.py` that bootstraps `sys.path`, or set `pythonpath` in `pytest.ini` |
| `import file mismatch` during collection | Two test files share a basename and neither directory has `__init__.py` | Rename the new file to something unique, such as `test_<module>_unit.py` |
| Coverage reports 0% | `--cov` was given a file path | Pass the importable module name or the containing directory |
| Async tests skipped or erroring | `pytest-asyncio` missing, or strict mode without markers | Install it and mark coroutine tests with `@pytest.mark.asyncio`, or set `asyncio_mode` in `pytest.ini` |
| Tests pass locally, fail in CI | Installed versions differ from the pins | Run the suite once against a clean install of the pinned `requirements.txt` |

## Adding the agent to another repo

Copy the agent and skill files from the required files table, keeping the `.github/agents/` and
`.github/skills/` layout. Commit them, reload VS Code, and the agent is available. Nothing else in
the repository needs to change, and the pipeline detects the language and test conventions on its
own.
