---
description: Analisa o(s) repositório(s) e propõe/cria backlog completo Epic → Feature → User Story no Azure Boards
argument-hint: [caminho(s) dos repositórios] [foco opcional]
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*), Read, Glob, Grep
---

Gerar backlog a partir do código. Siga a skill `azure-flow`. Entrada: $ARGUMENTS

1. Repositórios: caminhos informados, ou o diretório atual. Para cada um: README, docs, estrutura,
   manifestos (package.json, *.csproj, pom.xml, requirements…), rotas/telas/serviços, TODO/FIXME,
   issues óbvias de qualidade (testes ausentes, CI ausente).
2. `check` e `list --type Epic --all-states` / `list --type Feature` para não duplicar o que já existe.
3. Proponha a hierarquia em lista indentada:
   - Epics = grandes capacidades/objetivos de negócio.
   - Features = entregas por epic.
   - User Stories = "Como/quero/para" + critérios Dado/Quando/Então + story points sugeridos.
   - Marque o que já existe no board (reutilizar) vs novo.
4. **Peça confirmação** (o usuário pode remover/editar itens). Para lotes grandes, confirme por epic.
5. Crie de cima para baixo com `create --parent`, tag `azure-flow` em tudo. Use `--dry-run` se o
   usuário pedir para só simular.
6. Resumo final: contagem por tipo e link de cada Epic (`tree <epicId>`).
