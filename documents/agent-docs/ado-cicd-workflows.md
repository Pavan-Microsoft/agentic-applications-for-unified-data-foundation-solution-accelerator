# ADO CICD Workflows Agent

An interactive GitHub Copilot custom agent that scaffolds **Azure DevOps (ADO) CI/CD pipelines** for
a repository's **existing** infrastructure — Bicep, Terraform, or both — together with the
post-deployment steps and tests that follow a deployment.

The agent only generates the pipeline YAML that **runs** what the repository already contains. It
does **not** author Bicep/Terraform or application code, and it always asks for confirmation before
writing any files.

---

## Contents

- [Prerequisites](#prerequisites)
- [Setup instructions](#setup-instructions)
- [Recommended model](#recommended-model)
- [Folder structure guidance](#folder-structure-guidance)
- [How a run works](#how-a-run-works)
- [Demo instructions](#demo-instructions)

---

## Prerequisites

### Tooling

| Tool | Why it is needed | Check |
|---|---|---|
| **VS Code + GitHub Copilot Chat** | Hosts the custom agent | Agent dropdown lists custom agents |
| **jq** | The discovery scripts parse and emit JSON | `jq --version` |
| **Bash** | Runs the bundled skill scripts | `bash --version` |
| **Terraform** CLI *(optional)* | Only for Terraform repositories, during local validation | `terraform version` |

The agent runs `check-prereqs.sh` and reports anything missing — it does **not** install tools for
you. Only `jq` and Bash are required to generate the YAML; `terraform` is needed only for the
optional local validation of Terraform repositories.

### Repository

- A repository containing **existing** Bicep and/or Terraform infrastructure.

---

## Setup instructions

Copy **only** these items into the target accelerator repository alongside its existing agents and
skills:

| Path | Purpose |
|---|---|
| `.github/agents/ado-cicd-workflows.agent.md` | Registers the custom agent |
| `.github/skills/ado-cicd-bicep-workflows/` | Bicep CI/CD pipeline generator skill |
| `.github/skills/ado-cicd-terraform-workflows/` | Terraform CI/CD pipeline generator skill |
| `.github/skills/ado-cicd-post-deploy/` | Post-deploy / application-deploy + tests skill |

The resulting layout in the target repository is:

```
<target-repository>/
└── .github/
    ├── agents/
    │   └── ado-cicd-workflows.agent.md
    └── skills/
        ├── ado-cicd-bicep-workflows/
        │   ├── SKILL.md
        │   ├── references/
        │   ├── scripts/          # check-prereqs.sh, inspect-repo.sh, validate-pipelines.sh
        │   └── templates/        # azure-pipelines-bicep-ci.yml, -deploy.yml, infra-bicep.yml
        ├── ado-cicd-terraform-workflows/
        │   ├── SKILL.md
        │   ├── references/
        │   ├── scripts/          # check-prereqs.sh, inspect-repo-tf.sh, validate-pipelines.sh
        │   └── templates/        # azure-pipelines-terraform-ci.yml, -deploy.yml, infra-terraform.yml
        └── ado-cicd-post-deploy/
            ├── SKILL.md
            ├── references/
            ├── scripts/          # check-prereqs.sh, inspect-post-deploy.sh, discover-tests.sh, validate-pipelines.sh
            └── templates/        # azure-pipelines-post-deploy.yml
```

Then:

1. Open the target repository in VS Code and open the **GitHub Copilot Chat** window.
2. In the agent dropdown, select **ADO CICD Workflows**.

> Open the folder that **contains** `.github/` as the workspace root, so Copilot discovers the agent
> and skills.

---

## Recommended model

The agent declares its models in frontmatter and selects one automatically when you pick the agent —
**Claude Opus 5** if available, otherwise **GPT-5.6 Sol**.

---

## Folder structure guidance

The agent writes the generated pipelines to `.azuredevops/pipelines/` (or an existing pipelines
folder if the repo already uses one).

```
<repo>/
└── .azuredevops/
    └── pipelines/                              # generated output
        ├── azure-pipelines-bicep-ci.yml            # (Bicep repos)
        ├── azure-pipelines-bicep-deploy.yml
        ├── infra-bicep.yml
        ├── azure-pipelines-terraform-ci.yml        # (Terraform repos)
        ├── azure-pipelines-terraform-deploy.yml
        ├── infra-terraform.yml
        └── azure-pipelines-post-deploy.yml         # shared post-deploy stage
```

**What each file is**

- **`*-ci.yml`** — runs on every pull request: static infrastructure validation + unit tests. No
  Azure sign-in required.
- **`*-deploy.yml`** — runs on merge to the main branch, on a daily schedule, and on demand:
  provisions a fresh resource group, deploys, tests, then **always deletes the resource group**.
- **`infra-*.yml`** — the reusable provisioning step called by the deploy pipeline.
- **`azure-pipelines-post-deploy.yml`** — the shared stage that configures the deployed app and runs
  the end-to-end tests.

Only the pipelines for the flavor(s) the repo actually contains are generated.

---

## How a run works

1. **Discovery (read-only).** `inspect-repo.sh` / `inspect-repo-tf.sh` detect the infrastructure
   flavor, entrypoint, parameters, tests, and any existing pipelines, writing
   `.agent/tmp/repo-facts.json`.
2. **Approval gate.** The agent reports the detected stack and presents a single plan listing the
   exact pipeline files it will create. **Nothing is written until you approve.**
3. **Generation.** The agent renders the CI, deploy, reusable infra step, and post-deploy stage into
   `.azuredevops/pipelines/`.
4. **Validation gate.** The agent runs `validate-pipelines.sh` over the generated YAML and reports
   the result.
5. **Report.** The agent summarizes the detected stack and the generated files.

---

## Demo instructions

### Prompt

```
Set up CI/CD workflows for this repo.
```

### Steps

1. Complete [Setup instructions](#setup-instructions) in the target repository.
2. Select **ADO CICD Workflows** in the Copilot Chat agent dropdown; set **Allow All**.
3. Send the prompt.
4. Review the detected stack and the plan of exact pipeline files, then type **Approve** or **yes**.
5. Wait for generation and the validation gate.
6. Review the generated pipelines in the `.azuredevops/pipelines/` folder.

