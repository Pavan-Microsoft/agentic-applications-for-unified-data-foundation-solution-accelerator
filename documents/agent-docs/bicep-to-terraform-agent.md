# Bicep → Terraform Converter Agent

A GitHub Copilot custom agent that produces a **1:1 Terraform port** of an existing Bicep
infrastructure. The port is written to a new `infra_tf/` directory that **coexists** with the
original `infra/`; the Bicep is never modified.

The port preserves the **output contract** — every output the source `main.bicep` emits
also exists in `infra_tf/outputs.tf` with an equivalent value.

The agent authors HCL. It does **not** deploy, and it does not generate CI/CD workflows.

---

## Contents

- [Prerequisites](#prerequisites)
- [Setup instructions](#setup-instructions)
- [Recommended model](#recommended-model)
- [Folder structure guidance](#folder-structure-guidance)
- [How a conversion run works](#how-a-conversion-run-works)
- [Known limitations and issues](#known-limitations-and-issues)
- [Demo instructions](#demo-instructions)

---

## Prerequisites

### Tooling

| Tool | Why it is needed | Check |
|---|---|---|
| **VS Code + GitHub Copilot Chat** | Hosts the custom agent | Agent dropdown lists custom agents |
| **Azure CLI** with the Bicep extension | `inspect-bicep.sh` runs `az bicep build` | `az bicep version` |
| **jq** | The discovery script parses compiled ARM JSON | `jq --version` |
| **Terraform** ≥ 1.5 | The mandatory `fmt` / `init` / `validate` gate | `terraform version` |
| **Bash** | Both skill scripts are bash | see the Windows note below |

`inspect-bicep.sh` hard-fails with `ERROR: az CLI required` or `ERROR: jq required` if either is
missing, so verify both before the first run.

> **Windows users:** run the skill scripts under **Git Bash**
> (`C:\Program Files\Git\bin\bash.exe`). The `bash.exe` shipped in `System32` is a WSL relay and
> fails with `execvpe(/bin/bash) failed` when WSL is not configured. Ensure `jq` is on the Git Bash
> `PATH`.

### Repository

- A repository containing Bicep infrastructure, conventionally under `infra/`.
- No pre-existing Azure deployment is required. This agent does not perform state adoption.

---

## Setup instructions

Copy **only** these two items into the target accelerator repository, alongside its existing agents
and skills.

| Path | Purpose |
|---|---|
| `.github/agents/bicep-to-terraform.agent.md` | Registers the custom agent |
| `.github/skills/bicep-to-terraform/` | The complete converter skill — copy the entire directory |

Resulting layout in the target repository:

```
<target-repository>/
└── .github/
    ├── agents/
    │   └── bicep-to-terraform.agent.md
    └── skills/
        └── bicep-to-terraform/
            ├── SKILL.md
            ├── references/
            │   ├── bicep-to-terraform-mapping.md
            │   └── naming-conventions.md
            ├── scripts/
            │   ├── inspect-bicep.sh
            │   └── validate-module-layout.sh
            └── templates/
                ├── providers.tf
                ├── gitignore
                └── module/
                    ├── main.tf
                    ├── variables.tf
                    ├── outputs.tf
                    └── versions.tf
```

Then:

1. Open the target repository in VS Code and open the **GitHub Copilot Chat** window.
2. In the agent dropdown, select **Bicep to Terraform Converter**.

---

## Recommended model

Use a **top-tier reasoning model** (Claude Opus 5 or GPT-5.6-sol).

---

## Folder structure guidance

Everything generated lands under `infra_tf/`, mirroring the Bicep module hierarchy so the 1:1
mapping stays legible:

```
infra_tf/
  providers.tf              # terraform{} + required_providers + backend block + provider "azurerm"
  variables.tf              # one variable per Bicep param (+ subscription_id)
  main.tf                   # root resources and module calls mirroring main.bicep
  outputs.tf                # every Bicep root output, value-equivalent (contract-preserving)
  terraform.tfvars          # non-secret values for the selected deployment flavor
  <env>.tfvars              # per-stage values, from infra/params/<env>.bicepparam
  .gitignore                # REQUIRED — see the warning below
  modules/
    <source-area>/          # the Bicep path is preserved below modules/
      <module-name>/        # one directory per reachable local *.bicep module
        main.tf
        variables.tf
        outputs.tf
        versions.tf
```

**Rules the agent enforces**

- **One source module → one generated module.** A Bicep file called several times still produces a
  single directory, called several times. Modules are never flattened or combined.
- **Four files in every child module**, even when a file would be empty.
- **Provider config is root-only.** Child modules declare provider *requirements* in `versions.tf`;
  credentials and subscription live only in the root `providers.tf`.

> **Do not commit `.terraform/`.** `terraform init` downloads provider binaries of several hundred
> MB, which exceed GitHub's 100 MB file limit and will break `git push`. The generated
> `infra_tf/.gitignore` covers `.terraform/`, `*.tfstate*`, saved `tfplan`s, and CI-generated
> backend files, while deliberately **keeping `.terraform.lock.hcl` tracked** so provider versions
> stay pinned.

Runtime-only files never authored by this skill: `backend.tf` overrides, `backend.ci.hcl`,
`state-scope.auto.tfvars`, `.terraform/`, `*.tfstate*`, `tfplan`.

---

## How a conversion run works

1. **Flavor selection.** If the entrypoint is a router exposing multiple flavors (`bicep`, `avm`,
   `avm-waf`), the agent asks which single flavor to port. If only one implementation exists, or
   the prompt names a flavor and entrypoint, it proceeds without asking. **One flavor per run.**
2. **Discovery (read-only).** `inspect-bicep.sh` compiles every reachable local module and writes
   `.agent/tmp/bicep-facts.json` — parameters, ARM-resolved variables, resources, `existing`
   resources, module graph, outputs, and provider hints.
3. **Approval gate.** The agent presents the inventory, the preserved-output list, and the
   source-file → module mapping. **Nothing is written until you approve.**
4. **Authoring.** Root files, then the full mirrored module tree, then `terraform.tfvars`.
5. **Validation gate.** The agent runs `validate-module-layout.sh`, `terraform fmt -recursive`,
   `terraform init -backend=false`, and `terraform validate`, iterating until clean. When it hits a
   class of error not already covered, it fixes the port **and** appends a note to
   `references/bicep-to-terraform-mapping.md` so later runs avoid it.
6. **Report.** Inventory, output contract, generated files, deviations, validation results.

---

## Known limitations and issues

- **One flavor per run.** Converting both `bicep` and `avm` means two separate runs.
- **Authoring only — no runtime verification.** The agent never runs `terraform plan` or `apply`, so
  it can only prove syntax and provider-schema correctness. Errors that surface only at plan or
  apply time need a human in the loop. Paste the failure back to the same agent; it will analyse
  the error and apply the fix.
- **Testing coverage.** The agent has mainly been exercised against the `bicep` flavor. `avm` and
  `avm-waf` are supported but less proven.
- **Runtime.** A single flavor of one accelerator takes roughly **30–40 minutes**, depending on size.
- **Reliance on `mapping.md`.** Conversion accuracy depends heavily on
  `references/bicep-to-terraform-mapping.md`, and that approach has limits:
  - *It grows without bound.* Every newly discovered error class adds another entry, and a large
    reference consumes context the agent needs for the actual conversion.
  - *It is reactive, not preventive.* It only covers mistakes someone has already hit; a brand-new
    resource type or provider argument is still a first-time failure.
  - *It goes stale.* Provider arguments get deprecated, renamed, or flipped between releases, but
    nothing in the pipeline re-checks entries against the current provider schema.
  - *It drifts and can contradict itself.* As the file is edited by several people, older guidance
    can survive alongside newer guidance that supersedes it.
  - *Fixes do not propagate.* The skill is copied per repository, so a lesson learned in one
    accelerator stays in that copy until someone manually syncs the others.

  We are exploring other approaches.

---

## Demo instructions

### Prompt

```
Convert the existing Bicep infrastructure in this repository to Terraform.
```

### Steps

1. Complete [Setup instructions](#setup-instructions) in the target repository.
2. Select **Bicep to Terraform Converter** in the Copilot Chat agent dropdown; set **Allow All**.
3. Send the prompt.
4. If asked, choose the **single flavor** to convert.
5. Review the analysis and conversion plan, then type **Approve**.
6. Wait for generation and the validation gate (**~30–40 minutes** for a full accelerator).
7. Review the generated Terraform, `terraform.tfvars`, preserved outputs, deviations, and gate results.

### Expected result

- The agent inspects **before** requesting approval.
- Only the selected flavor is converted; the original Bicep is unchanged.
- Terraform and `terraform.tfvars` are generated under `infra_tf/`.
- All Bicep root outputs and parameter defaults are preserved.
- The layout and `terraform validate` gates pass.
- The agent does **not** run `terraform plan` or `terraform apply`.

### Optional: deploy locally to verify

The agent never deploys. Use these steps only to test in a **disposable Azure test subscription**.

1. In `infra_tf/providers.tf`, temporarily comment out the **backend block only**, keeping the
   surrounding `terraform` config, `required_version`, `required_providers`, and
   `provider "azurerm"` unchanged:

   ```hcl
   backend "azurerm" {
     use_oidc         = true
     use_azuread_auth = true
   }
   ```

   Without it, `terraform init -reconfigure` uses local state.

2. Sign in and deploy:

   ```bash
   cd infra_tf
   az login
   az account set --subscription "<subscription-id>"
   az account show --query "{name:name,id:id}" -o table

   terraform init -reconfigure
   terraform validate
   terraform plan -out=tfplan     # review the summary carefully
   terraform apply tfplan
   terraform output
   ```

3. **Restore the `backend "azurerm"` block** before committing or sharing the generated Terraform.

**If Terraform prompts for input** — a `var.<name>` / `Enter a value:` prompt means a required
input is missing. Add a non-secret value to `terraform.tfvars`, or set it for the shell:

```powershell
$env:TF_VAR_subscription_id     = "<subscription-id>"
$env:TF_VAR_resource_group_name = "<test-resource-group-name>"
terraform plan -out=tfplan
```

`terraform apply tfplan` applies the approved saved plan without re-prompting. Running
`terraform apply` *without* a saved plan asks for `yes` — review the plan before confirming. Note
that any plan saved **before** an HCL, tfvars, or state change is stale; regenerate it.

> Local state, `tfplan`, `.terraform/`, and backend configuration can contain sensitive deployment
> information. Keep them git-ignored and never commit them. Never commit secrets to
> `terraform.tfvars`.

---

## Reference

All paths below are relative to `.github/skills/bicep-to-terraform/`.

| Document | Contents |
|---|---|
| `SKILL.md` | The canonical process the agent follows |
| `references/bicep-to-terraform-mapping.md` | Construct/resource/function mapping, plan-time cardinality, azapi gotchas, apply-time failure triage |
| `references/naming-conventions.md` | `infra_tf/` layout, naming, tfvars, backend conventions |
| `scripts/inspect-bicep.sh` | Read-only discovery → `bicep-facts.json` (`schemaVersion: 3`) |
| `scripts/validate-module-layout.sh` | Structural and semantic gate over the generated tree |
