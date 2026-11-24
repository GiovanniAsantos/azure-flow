---
description: Reconcilia o board com o que foi feito nas sprints (resumos semanais + commits) — cria sprints faltantes, move cards, cria os que faltam e liga commits
argument-hint: <sprints ou período> [arquivos de resumo anexados] [--author <nome>]
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*), Bash(pandoc:*), Read, Glob, Grep
---

Reconciliar o board com o trabalho real das sprints. Siga a skill `azure-flow`. Entrada: $ARGUMENTS

1. **Fontes**
   - Resumos/relatórios anexados (docx, pdf, md): extraia o texto (`pandoc -t plain` para .docx)
     e monte, por sprint e por pessoa, a lista do que foi planejado e feito.
   - `sprints --last 12`: confira se as sprints do período existem e as datas.
   - `activity --since <início> --until <fim> --author "<nome>"` (repita `--author` para cada nome
     ou máquina da pessoa, ex.: o usuário do Windows que aparece como autor). Pergunte ao usuário
     quais nomes de autor são dele quando houver dúvida.
   - Cards do período: `list --all-states --mine`, cards das sprints envolvidas e os criados/alterados
     no período; `get <id>` para ver commits/branches já ligados.

2. **Diagnóstico**
   - Sprints que faltam no board.
   - Cards existentes na sprint errada (compare com a sprint dos commits e dos resumos).
   - Trabalho feito sem card (commits ou itens do resumo sem correspondente).
   - Commits não ligados a nenhum card.
   - Cards sem pai, sem tags específicas ou sem Story Points.

3. **Plano** — gere um arquivo `reorganizacao-<período>.md` com, por sprint:
   tabela "card → ação" e o bloco de comandos `ado ...` prontos (SHA completo + `--repo` nos
   `link-commit`). Itens já feitos são criados e depois fechados (`update <id> --state Closed`).
   Trabalho de outra pessoa continuado pelo usuário: Story atribuída ao dono + Task do usuário.
   Mostre o resumo e **peça confirmação**; deixe o usuário ajustar sprints, donos e títulos.

4. **Execução** (após o ok), nesta ordem:
   1. `sprint-create --name "Sprint N" --start ... --finish ... --team "<time>"` para as que faltam
      (exige admin; se falhar, oriente pela tela).
   2. `update <id> --sprint N --add-tags ... --module <repo>` e mudanças de estado aprovadas.
   3. `create ... --iteration N --module ... --tags ...` dos cards novos, guardando os ids.
   4. `link-commit <id> <sha> --repo <repo>` e `link-branch`.
   5. Confira sprint a sprint (cards, estado, responsável, nº de artefatos, tags).

5. **Hierarquia** — ofereça em seguida `/azure-flow:organize-backlog` para os cards que ficaram
   sem pai (Epic/Feature existentes ou novos).
