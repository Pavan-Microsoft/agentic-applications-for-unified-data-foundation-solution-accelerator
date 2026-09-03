---
title: ADO CICD Workflows
---

# ADO CICD Workflows Agent

An interactive GitHub Copilot agent that scaffolds **Azure DevOps (ADO) CI/CD pipelines** for a
repository's **existing** infrastructure — Bicep, Terraform, or both — together with the
post-deployment steps and tests that follow a deployment.

The agent only generates the pipeline YAML that *runs* what the repository already contains, and it
always asks for confirmation before writing any files.

## What it generates

For each infrastructure type it finds (Bicep, Terraform, or both), the agent creates two pipelines
plus a shared post-deploy stage:

| Pipeline | When it runs | What it does |
| --- | --- | --- |
| **CI** | On every pull request | Checks the infrastructure files are valid and runs the unit tests. |
| **Deploy** | On merge to the main branch, on a daily schedule, and on demand | Creates a fresh, uniquely-named resource group, deploys the whole solution and the app into it, runs the end-to-end tests, then **always deletes the resource group**. |
| **Post-deploy stage** | Inside the Deploy pipeline, right after provisioning | Configures the freshly deployed app and runs the end-to-end tests against the live app. |

## Prerequisites

The agent checks for these (via its `check-prereqs.sh`) and reports anything missing.

| Requirement | Required? | Notes |
| --- | --- | --- |
| `jq` and Git Bash | Required | The bundled `scripts/*.sh` are portable Bash (macOS Bash 3.2 + Windows Git Bash/WSL); `jq` parses the discovery output. |
| `az` CLI + `az devops` extension | Optional | Only for the optional setup steps (service-connection / variable-group guidance and pipeline validation) — not needed to generate the YAML. |
| `terraform` CLI | Optional | Only for Terraform repositories, during local validation. |

## Recommended model

The agent declares its models in frontmatter and selects one automatically when you pick the agent —
**Claude Opus 5** if available, otherwise **GPT-5.6 Sol**.

## Folder structure guidance

The agent and its three skills live under `.github/`. The pipelines it generates are written to
`.azuredevops/pipelines/` (or an existing pipelines folder if the repo already uses one):

```
<repo>/
├─ .github/
│  ├─ agents/
│  │  └─ ado-cicd-workflows.agent.md        # the agent (dropdown label: "ADO CICD Workflows")
│  └─ skills/
│     ├─ ado-cicd-bicep-workflows/
│     │  ├─ SKILL.md
│     │  ├─ templates/                       # azure-pipelines-bicep-ci.yml, -deploy.yml, infra-bicep.yml
│     │  ├─ scripts/                         # check-prereqs.sh, inspect-repo.sh, validate-pipelines.sh
│     │  └─ references/
│     ├─ ado-cicd-terraform-workflows/
│     │  ├─ SKILL.md
│     │  ├─ templates/                       # azure-pipelines-terraform-ci.yml, -deploy.yml, infra-terraform.yml
│     │  ├─ scripts/                         # check-prereqs.sh, inspect-repo-tf.sh, validate-pipelines.sh
│     │  └─ references/
│     └─ ado-cicd-post-deploy/
│        ├─ SKILL.md
│        ├─ templates/                       # azure-pipelines-post-deploy.yml
│        ├─ scripts/                         # inspect-post-deploy.sh, discover-tests.sh, ...
│        └─ references/
└─ .azuredevops/
   └─ pipelines/                             # generated output — the pipeline YAMLs the agent writes
      ├─ azure-pipelines-bicep-ci.yml
      ├─ azure-pipelines-bicep-deploy.yml
      ├─ azure-pipelines-post-deploy.yml
      └─ infra-bicep.yml
```

## Demo / how to use

1. Choose the accelerator repository where you want to run the agent.
2. Copy the `.github/agents/ado-cicd-workflows.agent.md` file and the `.github/skills/` folder (with
   all three skills) into that repository, using the layout above.
3. Open the repository in VS Code, then open the GitHub Copilot Chat window.
4. Click the Agent selection dropdown and select **ADO CICD Workflows**.
5. Set the chat permissions to **Allow All** so the agent runs its read-only discovery without
   repeated prompts.
6. In the chat, enter the prompt:

   ```
   Set up CI/CD workflows for this repo.
   ```

7. The agent runs discovery, reports the detected stack (infra flavor, entrypoint, tests, existing
   pipelines), and presents a single plan listing the exact pipeline files it will create.
8. Review the plan and, when prompted, type **Approve** or **yes**.
9. The agent generates and validates the YAMLs (CI, deploy, the reusable infra step, and the post-deploy
   stage).
