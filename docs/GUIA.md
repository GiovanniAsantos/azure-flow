# Guia de uso do azure-flow

Passo a passo para usar 100% do plugin, tanto em sessões do Claude Code na nuvem (claude.ai/code, app) quanto na sua máquina.

---

## 1. Sessão na nuvem (claude.ai/code ou app Claude)

### O que já está configurado (environment **Default**)

| Item | Onde fica | Observação |
|---|---|---|
| PAT do Azure DevOps | Network secret de `dev.azure.com` | O proxy injeta o token, que nunca aparece no chat nem em variável |
| `AZURE_DEVOPS_PAT=proxy-injected` | Variável do environment | Só um placeholder para o script saber que há credencial |
| `AZURE_DEVOPS_ORG=SoftwareHouseBrasil`, `AZURE_DEVOPS_PROJECT=ABA` | Variáveis do environment | Valem fora de um clone do Azure Repos |
| Instalação do plugin | Setup script | Roda se o repo `azure-flow` estiver na sessão |

### Ao abrir uma sessão nova

1. Crie a sessão no environment **Default** e **selecione o repositório `GiovanniAsantos/azure-flow`**. Sem esse repo na sessão, o plugin não é instalado.
2. Confirme que o plugin carregou: digite `/` e procure `azure-flow:start-work`. Se não aparecer, peça:
   "instale o plugin azure-flow a partir da pasta azure-flow".
3. Peça para clonar os repos do Azure em que vai trabalhar, por exemplo:
   "clone api-bpms e aba-frontend do Azure, branch feature/new-llm-aplication".
   O clone usa o mesmo PAT, sem configuração extra.
4. Trabalhe dentro do clone (o plugin detecta org/projeto/repo pelo `origin`).

> Mapeamentos de branch (`map`) ficam no git config do clone. Numa sessão nova, com clone novo,
> rode `/azure-flow:start-work --story <id> --branch <nome>` de novo para recriar o mapeamento
> (o link no board já existe, então só o mapeamento local é refeito).

---

## 2. Na sua máquina (Claude Code CLI, VS Code ou JetBrains)

```bash
/plugin marketplace add GiovanniAsantos/azure-flow
```

```bash
/plugin install azure-flow@azure-flow
```

Autenticação, escolha uma:

```bash
az login
```

ou, com um PAT (Work Items R/W + Code R/W):

```bash
export AZURE_DEVOPS_PAT="<seu token>"
```

Requisitos: `git` e Python 3.8+ (`python3`; no Windows, garanta que `python3` existe no PATH).

Para atualizar o plugin depois de mudanças no repo:

```bash
/plugin marketplace update azure-flow
```

---

## 3. O que você consegue fazer (comandos)

| Situação | Comando | O que acontece |
|---|---|---|
| Começar tarefa nova | `/azure-flow:start-work implementar exportação de relatório em CSV no BPMS` | Busca Epic/Feature existentes, propõe a hierarquia, cria a User Story após seu ok, cria a branch `feature/<id>-<slug>` a partir de `dev`/`develop`, envia, linka e muda para Active |
| Story já existe | `/azure-flow:start-work --story 9939` | Não cria card; cria ou reaproveita a branch e linka |
| Branch já existe sem id no nome | `/azure-flow:start-work --story 9939 --branch feature/new-llm-aplication` | Mapeia sem renomear (ou renomeia, se você preferir) e oferece linkar os commits antigos |
| Ver andamento | `/azure-flow:work-status` | Story, pai, commits com tipo CC e `#id`, pendências, progresso vs critérios de aceite |
| Terminar | `/azure-flow:finish-work` (ou `--draft`) | Push, PR no Azure Repos linkado à story, descrição com commits e checklist dos critérios; pergunta se move para Resolved |
| Organizar cards soltos | `/azure-flow:organize-backlog agente de IA` | Busca por palavra inteira, propõe Epic/Features, coloca soltos embaixo, sugere critérios, converte para Bug se pedido |
| Board atrasado / fim de sprint | `/azure-flow:sync-sprints sprints 80 a 83` (anexe os resumos semanais) | Cria sprints faltantes, move cards para a sprint certa, cria cards do trabalho sem card e liga commits |
| Correção ligada a card antigo | `/azure-flow:start-work bug: ...` e depois "ligue ao 9935" | Bug novo na sprint atual com link *Related* ao card antigo |
| Backlog a partir do código | `/azure-flow:plan-backlog api-cloud aba-frontend` | Lê os repos e propõe Epic → Feature → Story completos |

**Tags:** todo card criado recebe módulo (pelo repositório: `BPMS`, `Signature`, `Cloud`, `Frontend`...),
funcionalidade (`retencao`, `versoes-sistema`...) e natureza (`correcao`, `reteste-qa`, `i18n`...), além de
`azure-flow`. A grafia das tags que já existem no projeto é reaproveitada.

Você também pode pedir em linguagem natural ("quais cards do sprint 79 estão sem critério de aceite?",
"mova a 9941 para Resolved", "linke os commits da branch X na story Y"). A skill `azure-flow` ensina o
Claude a usar o CLI.

### Regras automáticas

- **Commits**: numa branch rastreada, o Claude só consegue commitar com cabeçalho Conventional Commits
  e o rodapé `Refs: #<id>`. Exemplo:

  ```
  feat(bpms): exporta relatório de atividades em CSV

  Refs: #9939
  ```

  O Azure Repos linka o commit à story quando você faz push.
- **Nada é criado ou alterado no board sem você confirmar** a proposta.
- Histórico nunca é reescrito: commits antigos são linkados por link de artefato.

### CLI direto (opcional)

```bash
python3 plugins/azure-flow/scripts/ado.py list --search "agente|IA" --words --in-description
```

Outros comandos: `check`, `types`, `tags`, `module`, `get`, `tree`, `children`, `create`, `update`
(`--sprint`, `--add-tags`), `comment`, `relate`/`unrelate`, `link-branch`, `map`/`unmap`,
`link-commit` (`--repo`), `link-commits`, `commits`, `activity`, `sprints`, `sprint-create`, `pr`, `slug`.
Ajuda: `ado.py <comando> -h`.

---

## 4. O que você vai precisar fazer de tempos em tempos

| Quando | O que fazer |
|---|---|
| PAT vence (30 dias) | Azure DevOps → User settings → Personal access tokens → **Regenerate** (mantém os escopos). Atualize na nuvem: menu do cloud environment → Edit → Network secrets → `dev.azure.com`; ou peça ao Claude "atualize o secret do Azure" para abrir o formulário. Na máquina, atualize `AZURE_DEVOPS_PAT` ou use `az login` |
| Erro 401/403 | Token vencido ou sem escopo **Work Items (Read & Write)** + **Code (Read & Write)**. O token de "Generate Git Credentials" só tem Code |
| Outro projeto além do ABA | Dentro de um clone do Azure Repos o projeto vem do `origin`; fora dele, ajuste `AZURE_DEVOPS_PROJECT` no environment |
| Mudou o plugin | Commit + push no repo `azure-flow`; sessões novas pegam a versão nova. Na máquina: `/plugin marketplace update azure-flow` |
| Começou sprint nova | Se ela não existir no board: `ado.py sprint-create --name "Sprint 84" --start ... --finish ... --team "ABA Team"` (admin) |
| Fim de sprint | `/azure-flow:sync-sprints` com o resumo da semana para conferir se tudo tem card e commit ligado |
| Bug não aparece no board | Team settings → Working with bugs → "Bugs are managed with requirements" |
| Azure Repos não linka commit | Project settings → Repositories → Settings: habilite o link de work items por menção (`#id`) |

---

## 5. Exemplo real (projeto ABA, novembro/2026)

- `/azure-flow:organize-backlog agente de IA`: 7 stories soltas agrupadas em um Epic com 3 Features,
  descrições e critérios escritos a partir do código, 53 commits antigos ligados.
- `/azure-flow:organize-backlog correção de erros em homologação, organizar como bug`: 4 stories
  convertidas em Bug com Repro Steps e Severity, agrupadas em Epic/Feature de qualidade.
- `/azure-flow:sync-sprints sprints 80 a 83`: 4 sprints criadas, 27 cards distribuídos nas sprints
  em que foram feitos, 10 cards novos para trabalho sem card, 46 commits ligados; em seguida
  `/azure-flow:organize-backlog` pendurou os 10 cards soltos em Epics/Features.
