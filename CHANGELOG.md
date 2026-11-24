# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), versões em [SemVer](https://semver.org/lang/pt-BR/).

## [0.3.0] - 2026-11-24

### Adicionado
- README reescrito para times Scrum, com descrição detalhada de cada comando, hooks, convenções, CLI e solução de problemas.
- Seção "Bugs no board" (configuração *Working with bugs*).
- `/organize-backlog` documenta conversão de tipo (ex.: User Story → Bug com Repro Steps e Severity).

## [0.2.0] - 2026-11-24

### Adicionado
- Suporte a Product Backlog Item (template Scrum) e comando `types`.
- `map`/`unmap` para branches existentes sem id no nome e `link-commits` para ligar commits antigos.
- `/organize-backlog` e busca por palavra inteira (`list --words --in-description --no-parent`).

### Corrigido
- `get` falhava em itens sem relações.

## [0.1.0] - 2026-11-24

### Adicionado
- Primeira versão: `/start-work`, `/work-status`, `/finish-work`, `/plan-backlog`, CLI `ado.py` (PAT, token Entra ID ou Azure CLI) e hooks de commit.
