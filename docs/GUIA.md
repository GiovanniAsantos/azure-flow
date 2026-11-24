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
| Organizar cards soltos | `/azure-flow:organize-backlog agente de IA` | Busca por palavra inteira, propõe Epic/Features, coloca soltos embaixo, sugere critérios |
| Backlog a partir do código | `/azure-flow:plan-backlog api-cloud aba-frontend` | Lê os repos e propõe Epic → Feature → Story completos |

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

Outros comandos: `check`, `get`, `tree`, `children`, `create`, `update`, `comment`, `link-branch`,
`map`, `unmap`, `link-commit`, `link-commits`, `commits`, `pr`, `slug`. Ajuda: `ado.py <comando> -h`.

---

## 4. O que você vai precisar fazer de tempos em tempos

| Quando | O que fazer |
|---|---|
| PAT vence (30 dias) | Azure DevOps → User settings → Personal access tokens → **Regenerate** (mantém os escopos). Atualize na nuvem: menu do cloud environment → Edit → Network secrets → `dev.azure.com`; ou peça ao Claude "atualize o secret do Azure" para abrir o formulário. Na máquina, atualize `AZURE_DEVOPS_PAT` ou use `az login` |
| Erro 401/403 | Token vencido ou sem escopo **Work Items (Read & Write)** + **Code (Read & Write)**. O token de "Generate Git Credentials" só tem Code |
| Outro projeto além do ABA | Dentro de um clone do Azure Repos o projeto vem do `origin`; fora dele, ajuste `AZURE_DEVOPS_PROJECT` no environment |
| Mudou o plugin | Commit + push no repo `azure-flow`; sessões novas pegam a versão nova. Na máquina: `/plugin marketplace update azure-flow` |
| Azure Repos não linka commit | Project settings → Repositories → Settings: habilite o link de work items por menção (`#id`) |

---

## 5. Estado atual do board (Agente de IA)

```
#10036 Epic: Agente de IA ABA
  #10037 Feature: Núcleo do Agente de IA ABA
    #9917 Criação de Agente de IA ABA                     (aba-ai-agent, dev)
  #10038 Feature: Base de conhecimento do Agente (Curadoria)
    #9924 Curadoria Agente IA ABA
  #10039 Feature: Integrações do Agente de IA com serviços ABA
    #9939 BPMS        api-bpms       feature/new-llm-aplication  11 commits linkados
    #9940 Assinatura  api-signature  feature/new-llm-aplication   2 commits linkados
    #9941 Cloud       api-cloud      feature/new-llm-aplication   7 commits linkados
    #9942 Contas      api-account    feature/new-llm-aplication   (sem commits além de dev)
    #9943 Frontend    aba-frontend   feature/new-llm-aplication  33 commits linkados
```

Todos os cards têm descrição e critérios de aceite.
