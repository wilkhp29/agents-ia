# Registro resumido da avaliação do fluxo de agentes

O registro canônico é JSON criado por `python3 scripts/agent_eval.py prepare --runs 3`; este resumo Markdown serve para revisão humana e pode ser salvo ao lado do JSON. Preencha apenas com evidência real. Não inclua PII, segredos ou dados de clientes.

| Campo | Valor |
|---|---|
| Conjunto de casos | `agent-workflow-v1` |
| Data/hora e fuso |  |
| SHA dos perfis/configuração |  |
| SHA-256 por perfil TOML |  |
| Commit do pacote + estado dirty/hash do diff |  |
| Runtime/modelo e versão |  |
| Ferramentas/mock e versões |  |
| Worktree/fixture descartável e evidência |  |
| Chamadas externas bloqueadas por mock fail-closed? |  |
| Avaliador |  |
| Casos selecionados e motivo |  |
| Resultado geral | `PENDING` |

| Caso/tentativa | Perfil carregado e hash conferidos? | Status | Juiz determinístico e saída | Transcript/trace | Tempo/custo observados | Achado/severidade |
|---|---|---|---|---|---|---|
| E1/1 |  | NOT RUN |  |  | N/A |  |
| E1/2 |  | NOT RUN |  |  | N/A |  |
| E1/3 |  | NOT RUN |  |  | N/A |  |

No JSON, `observed_profiles` em cada trial contém uma entrada por perfil de `required_profiles`: `{ "identity_verified": true, "sha256": "<SHA-256 observado>" }`. Cada hash deve coincidir com `profiles.sha256[<nome>]`. Um booleano geral sem esses registros por perfil não satisfaz a verificação.

## Síntese e limitações

- Hard-fail P0/P1 observado: `N/A` / evidência:
- Notas calculadas conforme a rubrica v1, ou `BLOCKED`:
- Casos repetidos e justificativa:
- Ferramentas ausentes, cobertura ou incerteza:
- Próxima ação e responsável:
- O resumo geral só pode ser `PASS` se todos os trials selecionados passaram e nenhuma evidência ficou pendente. A execução local do recorder não satisfaz esse requisito.
- Sem telemetria de custo/duração, use `N/A`; não estime.
