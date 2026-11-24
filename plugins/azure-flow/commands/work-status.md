---
description: Mostra a story da branch atual, a hierarquia e os commits rastreados
argument-hint: [--base <branch>]
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*)
---

Status do trabalho atual. Siga a skill `azure-flow`.

1. `python3 "$AZURE_FLOW_ADO" current` → sem id na branch: avise e sugira `/start-work`.
2. `get <id>` (estado, responsável, pai) e `get <parentId>` para mostrar Feature/Epic.
3. `commits $ARGUMENTS` → liste cada commit: short sha, tipo CC, escopo, resumo, refs.
   Marque com ⚠ commits sem `#<id>` ou fora do padrão Conventional Commits.
4. `git status -sb` → diga se há commits não enviados (ahead) ou alterações pendentes.
5. Resumo curto: progresso vs critérios de aceite da story (o que parece feito / faltando).
