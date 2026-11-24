---
description: Cria/reusa Epic → Feature → item de backlog (User Story/PBI, ver `types`) no Azure Boards, cria branch linkada e prepara commits rastreados
argument-hint: <descrição do trabalho> | --story <id> [--branch <nome existente>]
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*), Read, Glob, Grep
---

Iniciar trabalho rastreado no Azure DevOps. Siga a skill `azure-flow` (convenções + CLI).

Entrada do usuário: $ARGUMENTS

Passos:

1. **Pré-checagem**: `python3 "$AZURE_FLOW_ADO" config` e `git status --porcelain`.
   - Árvore suja → pergunte se deve fazer stash/commit antes de trocar de branch.
   - Faltando org/projeto/repo → peça ao usuário ou oriente a definir `AZURE_DEVOPS_*`.
   - Rode `check` uma vez; se falhar com 401/403, explique (PAT expirado/escopo) e pare.

2. **Story existente** (`--story <id>` ou o usuário citou um id): `get <id>` e `tree` do pai,
   confirme com o usuário e pule para o passo 5.

3. **Entender o contexto**: leia README, estrutura de pastas e os arquivos mais relacionados à
   descrição, para escrever itens concretos (módulos, telas, endpoints reais).

4. **Montar hierarquia**:
   - Busque épicos e features abertos relacionados: `list --type Epic --search <termo>`,
     `list --type Feature --search <termo>`, `tree <epicId>`.
   - Proponha: reutilizar ou criar Epic, reutilizar ou criar Feature, criar User Story (título,
     "Como/quero/para", critérios Dado/Quando/Então, tags específicas — módulo, funcionalidade, natureza — e story points sugeridos).
   - Mostre a proposta em lista indentada e **peça confirmação**. Só crie após "ok".
   - Crie de cima para baixo com `create ... --parent <id>`, guardando os ids retornados.
   - Se o trabalho continua um item já resolvido/entregue, ligue o novo ao antigo:
     `relate <novoId> <antigoId> --comment "<motivo>"`.

5. **Branch**:
   - Primeiro veja se já existe: branch atual (`current`), `--branch <nome>` informado, ou branches
     linkadas na story (`get <id>` → artefatos `...GB<branch>`). `git branch -a --list "*<nome>*"`.
   - **Branch existente com id no nome**: `git switch <branch>`; nada a mapear.
   - **Branch existente sem id no nome** (ex. `feature/new-llm-aplication`): pergunte ao usuário:
     a) *Mapear sem renomear* (padrão): `map <storyId> --branch <branch>` (git config local + link no board).
     b) *Renomear* para `feature/<storyId>-<slug>`: `git branch -m`, `git push -u origin <novo>`;
        apagar a branch antiga no remoto só com confirmação explícita (quebra PRs abertos e clones).
     Commits antigos já enviados: ofereça `link-commits <storyId> --dry-run` e depois sem `--dry-run`
     (links de artefato, sem reescrever histórico). Uma mesma branch em vários repos pode ser
     mapeada para stories diferentes, uma por repo.
   - **Branch nova**: `git fetch origin`; base = branch padrão do repo (`git symbolic-ref --short
     refs/remotes/origin/HEAD`, senão `origin/dev`/`origin/develop`/`origin/main`).
     Nome `feature/<storyId>-<slug>` (use `slug "<título>"`; `fix/` para Bug).
     `git switch -c <branch> <base>`, `git push -u origin <branch>`, `link-branch <storyId>`.
   - `update <storyId> --state Active` (atribua ao usuário com `--assign` se ele quiser).

6. **Resumo final**: links do Epic/Feature/Story, branch criada e lembrete do formato de commit:
   `feat(<scope>): <resumo>` + rodapé `Refs: #<storyId>`.
