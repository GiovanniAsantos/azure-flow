---
description: Organiza cards existentes de um tema em Epic → Feature → item de backlog (User Story/PBI, ver `types`), reaproveitando o que já existe
argument-hint: <tema> (ex: "agente de IA")
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*), Read, Glob, Grep
---

Organizar o backlog existente de um tema. Siga a skill `azure-flow`. Tema: $ARGUMENTS

1. `check`. Monte termos de busca do tema (sinônimos pt/en, nomes de repos/serviços), separados por `|`.
2. Busque por palavra inteira, em título e descrição:
   `list --search "<t1>|<t2>|..." --words --in-description --all-states`
   e, para achar soltos, `--no-parent`. Busque também Epics/Features existentes do tema
   (`list --type Epic --search ... --words`, `list --type Feature ...`) e use `tree` neles.
3. Para cada card encontrado, `get <id>`: estado, pai, filhos, branch/commits linkados
   (artefatos `vstfs:///Git/Ref/...GB<branch>`), descrição e critérios de aceite vazios.
4. Proponha em lista indentada:
   - Epic (reutilizar existente ou criar) e Features agrupando os cards por objetivo.
   - Para cada card existente: mover para qual Feature (`update <id> --parent <featureId>`).
   - Cards sem descrição/critérios: texto sugerido "Como/quero/para" + Dado/Quando/Então
     (leia o código dos repos linkados quando disponível para ser concreto).
   - Lacunas: stories que faltam para cobrir a Feature.
   - Branches sem id no nome compartilhadas por vários cards: apenas informe.
5. **Peça confirmação** e permita ajustes. Não feche/remova cards sem pedido explícito.
6. Execute de cima para baixo: `create` (tag `azure-flow`), depois `update --parent`, depois
   `update --description/--acceptance` aprovados. Mostre `tree <epicId>` no fim.
