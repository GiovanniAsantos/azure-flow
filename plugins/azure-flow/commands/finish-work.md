---
description: Envia a branch, abre PR no Azure Repos linkado à story e atualiza o estado
argument-hint: [--draft] [--target <branch>]
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*)
---

Finalizar o trabalho da branch atual. Siga a skill `azure-flow`. Argumentos: $ARGUMENTS

1. `current` → precisa de id; `git status --porcelain` → alterações pendentes? pergunte se commita.
2. `commits` → se houver commit sem `#<id>`/fora do padrão, avise antes de seguir.
3. `git push` (com `-u origin <branch>` se ainda não houver upstream).
4. Título do PR: Conventional Commits do tipo predominante, ex. `feat(auth): login com SSO (#1234)`.
   Descrição em markdown: resumo, lista de commits agrupada por tipo, critérios de aceite da story
   como checklist, como testar. Mostre ao usuário e confirme.
5. `pr --title "..." --description "..." [--draft] [--target ...]` → mostre o link.
6. Pergunte se deve mover a story para `Resolved` (`update <id> --state Resolved`) ou manter `Active`
   até o merge. Opcional: `comment <id> "PR !<prId> aberto: <url>"`.
