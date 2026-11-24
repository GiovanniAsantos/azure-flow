# azure-flow

Plugin do Claude Code para trabalhar com **Azure DevOps** (Azure Boards + Azure Repos, processo **Agile**, **Conventional Commits**).

Ao iniciar uma tarefa, o Claude:

1. busca ou cria **Epic → Feature → User Story** no Azure Boards (com "Como/quero/para" e critérios de aceite);
2. cria a branch `feature/<storyId>-<slug>`, envia e **linka** à story (seção Development);
3. move a story para **Active**;
4. garante que todo commit siga Conventional Commits com rodapé `Refs: #<storyId>` (o Azure Repos linka o commit à story no push);
5. lista commits/progresso e abre **PR** já ligado à story.

## Comandos

| Comando | O que faz |
|---|---|
| `/start-work <descrição>` ou `/start-work --story 123` | Hierarquia + branch + link + Active |
| `/work-status` | Story atual, pai, commits rastreados, pendências |
| `/finish-work [--draft]` | Push, PR linkado, atualiza estado |
| `/plan-backlog [caminhos]` | Lê os repositórios e propõe/cria backlog completo |
| `/organize-backlog <tema>` | Agrupa cards existentes do tema em Epic → Feature, move soltos para baixo e completa critérios |

**Branch que já existe** (ex. `feature/new-llm-aplication`, sem id no nome): `/start-work --story 123 --branch feature/new-llm-aplication` mapeia a branch à story sem renomear (git config local), linka no board e oferece linkar os commits antigos já enviados, sem reescrever histórico.

Um hook bloqueia `git commit` feito pelo Claude numa branch rastreada quando falta `#<id>` ou o cabeçalho não segue Conventional Commits.

## Instalação

```bash
/plugin marketplace add GiovanniAsantos/azure-flow
/plugin install azure-flow@azure-flow
```

Requisitos: `git` e Python 3.8+ (`python3` no PATH; no Windows, crie um alias ou instale o Python pela Microsoft Store/winget).

## Autenticação (escolha uma)

**A. Azure CLI / Entra ID (recomendado no trabalho, sem vencimento manual)**

```bash
az login
```

O script pede um token novo ao `az` a cada uso, sem PAT para renovar.

**B. Personal Access Token**

User settings → Personal access tokens → New token:

- Organization: sua org (ou *All accessible organizations*)
- Scopes: **Work Items (Read & Write)** e **Code (Read & Write)**

```bash
export AZURE_DEVOPS_PAT="<token>"   # coloque no ~/.bashrc, ~/.zshrc ou nas variáveis de usuário do Windows
```

Quando vencer: Azure DevOps → Personal access tokens → **Regenerate** (mantém os escopos) ou **Edit** para estender, e atualize a variável. Respostas HTTP 401/403 do plugin indicam token vencido ou sem escopo.

> "Generate Git Credentials" na tela de clone cria um PAT só com escopo **Code**: serve para `git`, mas não para criar work items.

## Configuração

Org, projeto e repo são detectados pelo remote `origin` (`https://dev.azure.com/org/proj/_git/repo`, SSH ou `*.visualstudio.com`). Variáveis opcionais:

| Variável | Uso |
|---|---|
| `AZURE_DEVOPS_ORG` / `AZURE_DEVOPS_PROJECT` / `AZURE_DEVOPS_REPO` | Sobrescrevem a detecção |
| `AZURE_DEVOPS_AREA` / `AZURE_DEVOPS_ITERATION` | Area/Iteration Path padrão dos novos itens |
| `AZURE_DEVOPS_TOKEN` | Token bearer Entra ID já obtido |

No Azure Repos, confira em *Project settings → Repositories → Settings* que o link de work items por menção (`#id`) em commits está ativo.

## CLI direto

```bash
python3 plugins/azure-flow/scripts/ado.py check
python3 plugins/azure-flow/scripts/ado.py list --type Epic --search pagamento
python3 plugins/azure-flow/scripts/ado.py create --type "User Story" --title "Login com SSO" --parent 120 --dry-run
python3 plugins/azure-flow/scripts/ado.py commits
```

## Testes

```bash
python3 -m unittest discover -s tests
```
