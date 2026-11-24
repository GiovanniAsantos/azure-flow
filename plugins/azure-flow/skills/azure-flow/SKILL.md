---
name: azure-flow
description: Conventions and CLI for working with Azure DevOps (Azure Boards work items + Azure Repos) in this plugin. Use whenever the user talks about epics, features, user stories, tasks, bugs, work items, the board/backlog, linking branches or commits to work items, or opening PRs on Azure DevOps.
---

# azure-flow

Azure DevOps workflow for **Scrum teams** (sprints, backlog), **Azure Repos**, **Conventional Commits**.

## CLI

All Azure DevOps calls go through the bundled stdlib-only script (JSON output):

```bash
python3 "$AZURE_FLOW_ADO" <command> [...]
```

If `$AZURE_FLOW_ADO` is empty, use the path printed by the SessionStart context
(`<plugin root>/scripts/ado.py`). On Windows use `python` if `python3` is missing.

| Command | Purpose |
|---|---|
| `config` | Resolved org/project/repo/branch/work item (no network) |
| `types` | Work item types + states of the project (run once to know the backlog item type) |
| `tags [--search x]` | Tags already used in the project |
| `module [--repo name]` | Module tags of a repository |
| `check` | Verify credentials + project + repo access, show process template |
| `list [--type Epic] [--search "a\|b"] [--words] [--in-description] [--no-parent] [--mine] [--all-states]` | Query work items (`--words` = whole words, avoids "IA" matching "criação") |
| `tree <id> [--depth 2]` | Epic → Feature → Story hierarchy |
| `children <id>` / `get <id>` | Inspect items |
| `create --type "User Story" --title ... --parent <id> --description ... --acceptance ... [--tags a,b] [--module repo] [--auto-module] [--points 3] [--priority 2] [--assign email] [--dry-run]` | Create item (tags normalized, `azure-flow` added) |
| `update <id> --state Active` (also `--title --description --acceptance --assign --parent --field Ref=val`) | Update item |
| `comment <id> "text"` | Add discussion comment |
| `relate <id> <targets...> [--type related\|predecessor\|successor\|duplicate\|duplicate-of\|parent\|child\|tests\|tested-by] [--comment]` / `unrelate` | Link work items to each other ("<targets> is the <type> of <id>"); `get` lists them under `links` |
| `link-branch <id> [--branch name]` | Link branch (Development section) |
| `link-commit <id> [sha]` | Link a pushed commit explicitly |
| `map <id> [--branch b] [--no-link]` / `unmap` | Tie an existing branch without id in its name to a work item (git config `branch.<b>.azureworkitem`) + link it |
| `link-commits [id] [--base origin/dev] [--dry-run]` | Link all pushed commits of the branch to its work item (no history rewrite) |
| `commits [--base origin/main]` | Commits of current branch + parsed CC type and `#refs` |
| `pr --title ... [--description ...] [--target main] [--draft]` | PR linked to the branch's work item |
| `slug "text"` | Branch-safe slug |

Org/project/repo come from the `origin` remote; override with `AZURE_DEVOPS_ORG`,
`AZURE_DEVOPS_PROJECT`, `AZURE_DEVOPS_REPO`. Auth: `AZURE_DEVOPS_PAT`, else
`AZURE_DEVOPS_TOKEN`, else Azure CLI (`az login`). On HTTP 401/403 tell the user the
credential likely expired or lacks a scope — never ask them to paste it in chat.

## Hierarchy (Scrum)

- **Epic** — business outcome / big capability (months). Title: noun phrase ("Autenticação corporativa").
- **Feature** — deliverable slice of an epic (1 sprint–1 release). Title: capability ("Login com SSO Entra ID").
Backlog item type depends on the project's process template — run `types` once:
- Scrum template → **Product Backlog Item** (`--type pbi`), estimate in `Microsoft.VSTS.Scheduling.Effort`
  (`--field Microsoft.VSTS.Scheduling.Effort=5`), states New → Approved → Committed → Done.
- Board with **User Story** (e.g. project ABA) → `--type story`, `--points`, states New → Active → Resolved → Closed.

- **Backlog item** (User Story / PBI) — user value, fits in a sprint. Title: short action; description in the form
  *Como <persona>, quero <ação>, para <benefício>*; acceptance criteria as a Given/When/Then
  (Dado/Quando/Então) list. Optional Story Points.
- **Task** — technical step under a story (optional). **Bug** — defect.

Rules:
1. Always search before creating (`list --type Epic --search ...`); reuse existing open items when they fit.
2. Never create items without showing the proposed hierarchy to the user and getting confirmation.
3. Write titles/descriptions in the user's language (default pt-BR).
4. Fix related to an already resolved item: same defect and its sprint still open → reopen it;
   new defect or item already delivered → new Bug in the current sprint + `relate <new> <old>`.
5. States: starting work = `Active` (User Story) / `Committed` (PBI); PR opened = keep it;
   done = `Resolved` (User Story) / `Done` (PBI). Put new backlog items in the current sprint
   (`--iteration`, e.g. `ABA\Sprint 79`) when the user is starting work now.

## Tags

Every created item gets 3–6 specific tags. Run `tags` once per session and reuse the existing
spelling; never create a synonym of an existing tag (`Signature`, not `Assinatura`).

1. **Module** (one per affected service): `--module <repo>` (e.g. `--module api-bpms` → `BPMS`) or
   `--auto-module` for the current repo; `module --repo <name>` shows the mapping. Vocabulary:
   `BPMS`, `Signature`, `Account`, `Cloud`, `Frontend`, `Gateway`, `Email`, `Orchestrator`,
   `AgentIA`, `InfraBanco`, `Corda API`. Epics/Features get the modules of all their children.
2. **Feature / subject** (kebab-case pt, ascii): what the work is about, e.g. `retencao`, `lixeira`,
   `versoes-sistema`, `relatorios`, `relatorios-agendados`, `ocr`, `classificacao`,
   `links-compartilhados`, `creditos-ia`, `curadoria`, `ciclo-de-planos`, `deploy-automatico`.
3. **Nature** (optional, kebab-case): `correcao`, `reteste-qa`, `homologacao`, `i18n`, `ux`,
   `performance`, `seguranca`, `testes`, `divida-tecnica`, `documentacao`.
4. `azure-flow` is added automatically.

Do not repeat the work item type as a tag (no `bug`, `feature`). Show the tags in the proposal so the
user can adjust them. Existing items: `update <id> --add-tags a,b --remove-tags c [--module repo]`.

## Branches

`<prefix>/<storyId>-<slug>` from the repo default branch:
- `feature/` for User Story, `fix/` for Bug, `chore/` for Task with no user value.
- Example: `feature/1234-login-sso`.

The work item id comes from the branch name; for existing branches without an id, from the
mapping created by `map` (local git config, per clone). Default branches here are often `dev` or
`develop`: always read the repo default instead of assuming `main`.

## Commits (Conventional Commits)

```
<type>(<scope>): <summary in imperative, ≤72 chars>

<optional body: why, not what>

Refs: #<storyId>
```

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert. `!` after type/scope
or a `BREAKING CHANGE:` footer for breaking changes. The `Refs: #<id>` footer makes Azure Repos link
the commit to the work item on push. A PreToolUse hook blocks `git commit` on a tracked branch when
the header is not Conventional Commits or the `#<id>` reference is missing.
