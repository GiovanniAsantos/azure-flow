---
description: Verifica os itens ativos do usuário, detecta o que já foi concluído/PR feito e propõe concluir Features/Epics quando todos os filhos estiverem feitos
argument-hint: (sem argumentos) ou <id do Epic/Feature para checar>
allowed-tools: Bash(python3:*), Bash(python:*), Bash(git:*), Read, Glob, Grep
---

Concluir automaticamente Features/Epics cujos filhos já terminaram. Siga a skill `azure-flow`. Argumento (opcional): $ARGUMENTS

1. `check`. Se um id foi passado em $ARGUMENTS, pule para o passo 3 usando esse id como ponto de partida.
2. Sem id: `list --mine --all-states` para achar os itens ativos/resolvidos do usuário
   (User Story/PBI em `Active`/`Committed`/`Resolved`/`Done`). Para cada um, pegue o pai
   (`get <id>`) e monte o conjunto de Features/Epics candidatos a checar.
3. Para cada Feature candidata: `tree <featureId>` (ou `children <featureId>`) e confirme o estado
   de cada filho (User Story/PBI/Bug). Considere "terminado" = `Resolved`/`Closed` (User Story) ou
   `Done`/`Closed` (PBI). Para cada story ainda aberta, cheque também se já existe PR mesclado
   mas o item não foi atualizado: `get <id>` mostra artefatos de branch/commit linkados; se a
   branch não existe mais (mesclada/apagada) e os commits estão todos na base, trate como
   terminada e sinalize para o usuário atualizar o estado antes de concluir a Feature.
4. Se **todos** os filhos de uma Feature estão terminados:
   - Proponha `update <featureId> --state Resolved|Done` (conforme o template do projeto).
   - Depois repita o mesmo teste para o Epic pai: se todas as suas Features estão terminadas,
     proponha concluir o Epic também.
5. Se algum filho não está terminado, **não proponha fechar** o pai; apenas liste quais filhos
   ainda faltam (id, título, estado).
6. **Peça confirmação** antes de qualquer `update --state`. Nunca feche um item sozinho sem o
   usuário confirmar — mesmo que todos os filhos pareçam prontos. Não remova/feche itens que não
   fazem parte do escopo checado.
7. Resumo final: lista do que foi concluído, do que ficou pendente (com motivo) e `tree` dos
   Epics tocados.
