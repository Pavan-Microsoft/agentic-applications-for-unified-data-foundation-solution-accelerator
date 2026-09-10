---
name: code-testing-extensions
description: >-
  Provides file paths to language-specific extension files for the code-testing
  pipeline. Supports .NET and Python only. Do not use directly — invoked by
  code-testing agents and skills that need language-specific references.
user-invocable: false
disable-model-invocation: true
license: MIT
---

# Code Testing Extensions

This skill provides access to language-specific guidance files used by the code-testing pipeline. Call this skill to get the file paths, then read the relevant file for your target language. Only .NET and Python are supported.

## Available Extension Files

| File | Language | Contents |
|------|----------|----------|
| [extensions/dotnet.md](extensions/dotnet.md) | .NET (C#/F#/VB) | Build commands, test commands, project reference validation, common CS error codes, MSTest template |
| [extensions/python.md](extensions/python.md) | Python | Framework-adaptive test commands (pytest, custom runners), project layout detection, mocking guidelines, common errors |
| [extensions/dotnet-examples.md](extensions/dotnet-examples.md) | .NET (C#/F#/VB) | Concrete pipeline examples: sample research output, plan, generated tests, fix cycles, final report |
| [extensions/python-examples.md](extensions/python-examples.md) | Python | Concrete pipeline examples (pytest): research, plan, generated test file, fix cycles, final report |

## Usage

Read the appropriate extension file for the target language before writing test code. When an `<language>-examples.md` file exists for the target language, read it alongside the base extension to see a concrete end-to-end pipeline walkthrough (research output, plan, generated tests, fix cycles, final report).
