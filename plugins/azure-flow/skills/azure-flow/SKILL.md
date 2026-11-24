---
name: azure-flow
description: Conventions and CLI for working with Azure DevOps (Azure Boards work items + Azure Repos) in this plugin. Use whenever the user talks about epics, features, user stories, tasks, bugs, work items, the board/backlog, linking branches or commits to work items, or opening PRs on Azure DevOps.
---

# azure-flow

Azure DevOps workflow: **Agile process**, **Azure Repos**, **Conventional Commits**.

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
| `check` | Verify credentials + project + repo access, show process template |
| `list [--type Epic] [--search "a\|b"] [--words] [--in-description] [--no-parent] [--mine] [--all-states]` | Query work items (`--words` = whole words, avoids "IA" matching "criação") |
| `tree <id> [--depth 2]` | Epic → Feature → Story hierarchy |
| `children <id>` / `get <id>` | Inspect items |
| `create --type "User Story" --title ... --parent <id> --description ... --acceptance ... [--tags a,b] [--points 3] [--priority 2] [--assign email] [--dry-run]` | Create item |
| `update <id> --state Active` (also `--title --description --acceptance --assign --parent --field Ref=val`) | Update item |
| `comment <id> "text"` | Add discussion comment |
| `link-branch <id> [--branch name]` | Link branch (Development section) |
| `link-commit <id> [sha]` | Link a pushed commit explicitly |
| `commits [--base origin/main]` | Commits of current branch + parsed CC type and `#refs` |
| `pr --title ... [--description ...] [--target main] [--draft]` | PR linked to the branch's work item |
| `slug "text"` | Branch-safe slug |

Org/project/repo come from the `origin` remote; override with `AZURE_DEVOPS_ORG`,
`AZURE_DEVOPS_PROJECT`, `AZURE_DEVOPS_REPO`. Auth: `AZURE_DEVOPS_PAT`, else
`AZURE_DEVOPS_TOKEN`, else Azure CLI (`az login`). On HTTP 401/403 tell the user the
credential likely expired or lacks a scope — never ask them to paste it in chat.

## Hierarchy (Agile)

- **Epic** — business outcome / big capability (months). Title: noun phrase ("Autenticação corporativa").
- **Feature** — deliverable slice of an epic (1 sprint–1 release). Title: capability ("Login com SSO Entra ID").
- **User Story** — user value, fits in a sprint. Title: short action; description in the form
  *Como <persona>, quero <ação>, para <benefício>*; acceptance criteria as a Given/When/Then
  (Dado/Quando/Então) list. Optional Story Points.
- **Task** — technical step under a story (optional). **Bug** — defect.

Rules:
1. Always search before creating (`list --type Epic --search ...`); reuse existing open items when they fit.
2. Never create items without showing the proposed hierarchy to the user and getting confirmation.
3. Write titles/descriptions in the user's language (default pt-BR).
4. States (Agile): New → Active → Resolved → Closed. Starting work = `Active`; PR opened = keep `Active`;
   PR merged/done = `Resolved`.

## Branches

`<prefix>/<storyId>-<slug>` from the repo default branch:
- `feature/` for User Story, `fix/` for Bug, `chore/` for Task with no user value.
- Example: `feature/1234-login-sso`.

The work item id is always parsed from the branch name.

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
