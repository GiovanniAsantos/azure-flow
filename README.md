# azure-flow

Plugin do [Claude Code](https://code.claude.com) que conecta o seu fluxo **Scrum** no **Azure DevOps** (Azure Boards + Azure Repos) ao código: o Claude cria e organiza o backlog da sprint, abre branches ligadas aos itens, garante commits rastreáveis em **Conventional Commits** e abre pull requests já vinculados ao card.

- Backlog em camadas: **Epic → Feature → item de backlog → Task/Bug**
- Branch por item: `feature/<id>-<slug>`, linkada ao card (seção *Development*)
- Commit sempre com `Refs: #<id>`: o Azure Repos liga o commit ao card no push
- Nada é criado ou alterado no board sem você aprovar a proposta
- Histórico do git nunca é reescrito: commits antigos são ligados por link de artefato

---

## Sumário

- [Scrum com o azure-flow](#scrum-com-o-azure-flow)
- [Instalação](#instalação)
- [Autenticação](#autenticação)
- [Comandos](#comandos)
  - [/azure-flow:start-work](#azure-flowstart-work)
  - [/azure-flow:work-status](#azure-flowwork-status)
  - [/azure-flow:finish-work](#azure-flowfinish-work)
  - [/azure-flow:plan-backlog](#azure-flowplan-backlog)
  - [/azure-flow:organize-backlog](#azure-floworganize-backlog)
- [Regras automáticas (hooks)](#regras-automáticas-hooks)
- [Convenções](#convenções)
- [CLI `ado.py`](#cli-adopy)
- [Configuração](#configuração)
- [Bugs no board](#bugs-no-board)
- [Problemas comuns](#problemas-comuns)
- [Desenvolvimento](#desenvolvimento)

---

## Scrum com o azure-flow

| Momento da sprint | O que usar | Resultado no Azure DevOps |
|---|---|---|
| **Refinamento / Sprint Planning** | `/azure-flow:plan-backlog`, `/azure-flow:organize-backlog` | Epics, Features e itens de backlog com "Como/quero/para", critérios de aceite e estimativa, na sprint certa |
| **Início de uma tarefa da sprint** | `/azure-flow:start-work` | Item em andamento, branch criada e linkada |
| **Durante a sprint / Daily** | `/azure-flow:work-status` | Progresso do item, commits rastreados, o que falta dos critérios de aceite |
| **Fim da tarefa / Review** | `/azure-flow:finish-work` | Pull request linkado ao item, descrição com commits e checklist dos critérios |
| **Correções encontradas pela QA** | `/azure-flow:organize-backlog <tema>` | Cards de correção convertidos em **Bug** e agrupados sob Epic/Feature |

### Tipos de item de backlog

O método é Scrum independentemente do *template de processo* do projeto no Azure. O plugin descobre o tipo usado (comando `types`):

| Template do projeto | Item de backlog | Estados | Estimativa |
|---|---|---|---|
| Scrum | Product Backlog Item | New → Approved → Committed → Done | `Effort` |
| Agile (ex.: projeto ABA) | User Story | New → Active → Resolved → Closed | `Story Points` |

---

## Instalação

No Claude Code (CLI, VS Code, JetBrains ou claude.ai/code):

```bash
/plugin marketplace add GiovanniAsantos/azure-flow
```

```bash
/plugin install azure-flow@azure-flow
```

Requisitos: `git` e Python 3.8+ com `python3` no PATH. O plugin usa apenas a biblioteca padrão do Python.

Para atualizar:

```bash
/plugin marketplace update azure-flow
```

Sessões na nuvem (claude.ai/code): veja o passo a passo em [docs/GUIA.md](docs/GUIA.md).

---

## Autenticação

Escolha uma opção. O plugin tenta, nesta ordem: `AZURE_DEVOPS_PAT`, `AZURE_DEVOPS_TOKEN`, Azure CLI.

**A. Azure CLI / Entra ID (recomendado, sem renovação manual)**

```bash
az login
```

**B. Personal Access Token**

Azure DevOps → *User settings* → *Personal access tokens* → *New token*:

- Organization: a sua (ou *All accessible organizations*)
- Scopes: **Work Items (Read & Write)** e **Code (Read & Write)**

```bash
export AZURE_DEVOPS_PAT="<token>"
```

Quando o token vencer, use *Regenerate* (mantém os escopos) e atualize a variável. O token de *Generate Git Credentials* (tela de clone) só tem escopo **Code** e não cria work items.

---

## Comandos

Todos os comandos mostram uma proposta e pedem confirmação antes de escrever no board.

### `/azure-flow:start-work`

**Para que serve:** começar uma tarefa da sprint com rastreabilidade completa, do card até o commit.

```
/azure-flow:start-work exportar relatório de atividades em CSV no BPMS
/azure-flow:start-work --story 9939
/azure-flow:start-work --story 9939 --branch feature/new-llm-aplication
```

| Argumento | Efeito |
|---|---|
| `<descrição>` | Procura Epic/Feature relacionados e propõe criar o item de backlog que falta |
| `--story <id>` | Usa um item que já existe, sem criar card |
| `--branch <nome>` | Usa uma branch que já existe em vez de criar outra |

**O que faz:**

1. Confere configuração, credencial e se há alterações não commitadas.
2. Lê README, estrutura e arquivos relacionados para escrever um card concreto.
3. Busca Epics e Features abertos do assunto e propõe reaproveitar ou criar. O item de backlog vem com "Como/quero/para", critérios Dado/Quando/Então, tags e estimativa sugerida.
4. Após sua aprovação, cria de cima para baixo.
5. Branch:
   - **nova**: `feature/<id>-<slug>` (ou `fix/` para Bug) a partir da branch padrão do repo (`dev`, `develop` ou `main`), com push e link no card;
   - **existente com id no nome**: só troca para ela;
   - **existente sem id no nome**: mapeia a branch ao card sem renomear (git config local) ou renomeia, se você preferir; oferece ligar os commits antigos já enviados.
6. Move o item para em andamento (`Active` ou `Committed`).
7. Mostra os links e o formato de commit esperado.

### `/azure-flow:work-status`

**Para que serve:** saber em que pé está a tarefa atual, ideal para a Daily.

```
/azure-flow:work-status
/azure-flow:work-status --base origin/develop
```

**O que mostra:**

- item da branch atual, estado, responsável, Feature e Epic pais;
- commits da branch com tipo e escopo Conventional Commits e os `#id` referenciados;
- alerta ⚠ em commits sem `#id` ou fora do padrão;
- commits ainda não enviados e alterações pendentes;
- progresso estimado frente aos critérios de aceite.

### `/azure-flow:finish-work`

**Para que serve:** encerrar a tarefa e levar para revisão.

```
/azure-flow:finish-work
/azure-flow:finish-work --draft
/azure-flow:finish-work --target develop
```

**O que faz:**

1. Avisa sobre alterações não commitadas e commits fora do padrão.
2. Faz push da branch.
3. Monta o PR: título Conventional Commits (ex.: `feat(bpms): exporta relatório em CSV (#9939)`), descrição com resumo, commits agrupados por tipo, critérios de aceite como checklist e como testar.
4. Abre o PR no Azure Repos já vinculado ao item (após sua aprovação).
5. Pergunta se move o item para `Resolved`/`Done` e pode registrar o PR em comentário no card.

### `/azure-flow:plan-backlog`

**Para que serve:** montar o backlog a partir do código, no refinamento ou no início de um projeto.

```
/azure-flow:plan-backlog
/azure-flow:plan-backlog api-cloud aba-frontend
/azure-flow:plan-backlog api-bpms foco em relatórios
```

**O que faz:**

1. Lê cada repositório: README, documentação, manifestos, rotas, telas, serviços, TODO/FIXME, lacunas de testes e CI.
2. Consulta o board para não duplicar o que já existe.
3. Propõe Epics (objetivos), Features (entregas) e itens de backlog com critérios e estimativa, marcando o que é novo e o que será reaproveitado.
4. Você remove ou ajusta itens; em lotes grandes a confirmação é por Epic.
5. Cria tudo com a tag `azure-flow` (ou só simula, com `--dry-run`).

### `/azure-flow:organize-backlog`

**Para que serve:** pôr ordem em cards que já existem: soltos, sem pai, sem critérios ou do tipo errado.

```
/azure-flow:organize-backlog agente de IA
/azure-flow:organize-backlog correção de erros em homologação, organizar como bug
```

**O que faz:**

1. Busca por palavra inteira, em título e descrição, com sinônimos (ex.: "IA" não casa com "criação").
2. Para cada card: estado, pai, filhos, branches e commits ligados, campos vazios.
3. Propõe:
   - Epic e Features que agrupam os cards (reaproveitando os existentes);
   - para onde cada card vai;
   - descrição e critérios para os cards vazios, escritos a partir do código e dos commits;
   - conversão de tipo quando pedido (ex.: User Story → **Bug**, com *Repro Steps* e *Severity*);
   - commits de correção que ainda não estão ligados aos cards;
   - lacunas: itens que faltam para cobrir a Feature.
4. Executa só o que você aprovar e mostra a árvore final. Não fecha nem remove cards sem pedido explícito.

---

## Regras automáticas (hooks)

| Hook | Quando | O que faz |
|---|---|---|
| `SessionStart` | Ao abrir o Claude | Informa o caminho do CLI e o item da branch atual |
| `PreToolUse` (Bash) | Quando o Claude roda `git commit` numa branch ligada a um item | Bloqueia se o cabeçalho não seguir Conventional Commits ou faltar `#<id>`, e explica como corrigir |

Branches sem item ligado não são afetadas.

---

## Convenções

**Branches:** `feature/<id>-<slug>` para itens de backlog, `fix/<id>-<slug>` para Bug, `chore/<id>-<slug>` para Task técnica. O id é lido do nome; branches antigas sem id podem ser mapeadas com `map`.

**Commits:**

```
<tipo>(<escopo>): <resumo no imperativo, até 72 caracteres>

<corpo opcional: por quê>

Refs: #<id>
```

Tipos: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Use `!` ou o rodapé `BREAKING CHANGE:` para mudanças incompatíveis.

**Tags:** cada item recebe de 3 a 6 tags, reaproveitando a grafia das que já existem no projeto:

| Grupo | Como é definido | Exemplos |
|---|---|---|
| Módulo | Pelo repositório (`--module api-bpms`, `--auto-module`) | `BPMS`, `Signature`, `Account`, `Cloud`, `Frontend`, `Gateway`, `Email`, `Orchestrator`, `AgentIA` |
| Funcionalidade | Assunto do trabalho, kebab-case | `retencao`, `versoes-sistema`, `relatorios-agendados`, `ocr`, `creditos-ia` |
| Natureza (opcional) | Tipo de esforço, kebab-case | `correcao`, `reteste-qa`, `i18n`, `performance`, `seguranca` |
| Plugin | Automática | `azure-flow` |

O mapa repositório → módulo pode ser ampliado com um `.azure-flow.json` na raiz do repo (`{"modules": {"meu-repo": ["MeuModulo"]}}`).

**Cards:** títulos e descrições no idioma do time; item de backlog no formato "Como <persona>, quero <ação>, para <benefício>"; critérios em Dado/Quando/Então.

---

## CLI `ado.py`

Os comandos usam `plugins/azure-flow/scripts/ado.py`, que também pode ser usado direto. Saída sempre em JSON.

| Comando | Para que serve |
|---|---|
| `config` | Mostra org, projeto, repo, branch e item resolvidos (sem rede) |
| `check` | Testa credencial, projeto e repositório |
| `types` | Lista tipos e estados do projeto e diz qual é o item de backlog |
| `list` | Consulta itens: `--type`, `--search "a\|b"`, `--words`, `--in-description`, `--no-parent`, `--mine`, `--all-states` |
| `get <id>` / `tree <id>` / `children <id>` | Detalhe de um item, árvore de filhos, filhos diretos |
| `sprints` / `sprint-create` | Lista sprints com datas / cria sprint e adiciona ao time (`--name`, `--start`, `--finish`, `--team`; exige admin) |
| `tags` / `module` | Tags já usadas no projeto / tags de módulo de um repositório |
| `create` | Cria item: `--type`, `--title`, `--parent`, `--description`, `--acceptance`, `--tags`, `--module`, `--auto-module`, `--points`, `--priority`, `--assign`, `--field`, `--dry-run` |
| `update <id>` | Altera sprint (`--sprint 80`), estado, título, descrição, critérios, responsável, pai, tags (`--add-tags`, `--remove-tags`, `--module`) ou qualquer campo (`--field Ref=valor`) |
| `comment <id> "texto"` | Comenta no card |
| `relate <id> <outros...>` | Liga cards entre si: `--type related` (padrão), `predecessor`, `successor`, `duplicate`, `duplicate-of`, `parent`, `child`, `tests`, `tested-by`; `--comment`, `--dry-run` |
| `unrelate <id> <outros...>` | Remove esses links (`--type` opcional) |
| `link-branch <id>` | Liga uma branch ao card |
| `map <id>` / `unmap` | Associa uma branch existente sem id no nome a um card |
| `link-commit <id> [sha] [--repo nome]` | Liga um commit ao card (com `--repo` e SHA completo, funciona fora do clone) |
| `link-commits [id]` | Liga todos os commits enviados da branch ao card (`--dry-run` para simular) |
| `commits` | Commits da branch com tipo, escopo e `#id` |
| `pr` | Abre PR vinculado ao card (`--title`, `--description`, `--target`, `--draft`) |
| `slug "texto"` | Gera o trecho do nome de branch |

Exemplos:

```bash
python3 plugins/azure-flow/scripts/ado.py types
```

```bash
python3 plugins/azure-flow/scripts/ado.py list --search "agente|IA" --words --in-description --no-parent
```

```bash
python3 plugins/azure-flow/scripts/ado.py relate 10210 9935 --comment "Ajuste após correção de retenção"
```

```bash
python3 plugins/azure-flow/scripts/ado.py create --type story --title "Exportar relatório em CSV" --parent 10039 --dry-run
```

---

## Configuração

Org, projeto e repositório vêm do remote `origin` (`https://dev.azure.com/org/projeto/_git/repo`, SSH ou `*.visualstudio.com`).

| Variável | Uso |
|---|---|
| `AZURE_DEVOPS_PAT` | Personal Access Token |
| `AZURE_DEVOPS_TOKEN` | Token bearer Entra ID já obtido |
| `AZURE_DEVOPS_ORG` / `AZURE_DEVOPS_PROJECT` / `AZURE_DEVOPS_REPO` | Usadas quando não há remote do Azure Repos (o remote do clone sempre vence) |
| `AZURE_DEVOPS_AREA` / `AZURE_DEVOPS_ITERATION` | Area Path e sprint padrão dos novos itens |

No Azure Repos, confirme em *Project settings → Repositories → Settings* que a menção de work items (`#id`) em commits está habilitada.

---

## Card novo ou reabrir?

Correção ligada a um item já resolvido:

| Situação | Recomendação |
|---|---|
| Mesmo defeito, correção incompleta, sprint do card ainda aberta | Reabrir o item (`/azure-flow:start-work --story <id>`) |
| Defeito novo no mesmo módulo | Criar Bug novo e ligar ao antigo: `relate <novo> <antigo>` |
| Item já entregue (sprint fechada ou release feita) | Criar item novo na sprint atual, ligado ao antigo |

Pequenas correções (ex.: tradução faltando) podem ir num commit com `Refs: #<id>` do Bug relacionado.

## Bugs no board

Se o time estiver configurado com *Bugs are managed with tasks*, um Bug só aparece no Taskboard como filho de um item de backlog, e some do board quando fica sob uma Feature. Para ver Bugs como cards no backlog e no board:

*Board ou Backlog* → ⚙ *Configure team settings* → **Working with bugs** → **Bugs are managed with requirements** → *Save* (por time; exige admin do time).

Enquanto isso, os Bugs ficam visíveis pelo link direto, pela aba *Related Work* da Feature ou por uma query `Work Item Type = Bug`.

---

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| HTTP 401/403 | Token vencido ou sem escopo Work Items | Regenere o PAT com Work Items + Code, ou `az login` |
| `missing config: AZURE_DEVOPS_ORG...` | Fora de um clone do Azure Repos | Defina as variáveis `AZURE_DEVOPS_*` |
| Commit não aparece no card | Menção `#id` desabilitada no repo ou commit sem push | Habilite nas configurações do repo; use `link-commits` |
| Commit bloqueado pelo hook | Mensagem fora do padrão ou sem `Refs: #<id>` | Ajuste a mensagem conforme o exemplo do aviso |
| Bug sumiu do board | Configuração *Working with bugs* | Veja [Bugs no board](#bugs-no-board) |

---

## Desenvolvimento

```
.claude-plugin/marketplace.json     marketplace (lista o plugin)
plugins/azure-flow/
  .claude-plugin/plugin.json        manifesto do plugin
  commands/                         slash commands
  skills/azure-flow/SKILL.md        convenções e referência do CLI para o Claude
  hooks/                            SessionStart e validação de commit
  scripts/ado.py                    CLI do Azure DevOps (só biblioteca padrão)
tests/                              testes offline
docs/GUIA.md                        passo a passo de uso (nuvem e local)
```

```bash
python3 -m unittest discover -s tests
```

```bash
claude plugin validate .
```

Histórico de versões: [CHANGELOG.md](CHANGELOG.md). Licença: [MIT](LICENSE).
