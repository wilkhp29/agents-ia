# Observabilidade de agentes

## Capacidade disponível

O piloto agora coleta métricas somente para tarefas iniciadas pelo wrapper local [`scripts/codex_runtime_capture.py`](../scripts/codex_runtime_capture.py). Ele executa `codex exec --ignore-user-config --json --ephemeral`, lê JSONL em streaming e persiste apenas o contrato allowlist v2 [`schemas/codex-runtime-metric.schema.json`](../schemas/codex-runtime-metric.schema.json) em `logs/runtime/codex_runs.jsonl` (arquivo ignorado pelo Git, permissão local 0600). `--ignore-user-config` deixa de carregar integrações MCP e plugins do config global; autenticação segue disponível e o config de projeto fornece papéis e multi-agent. O wrapper não grava nem repassa ao log o prompt, resposta, argumentos/resultados de ferramentas ou eventos crus. A resposta final é mostrada somente ao chamador.

**Escopo da instrumentação:** somente tarefas pelo Codex CLI local 0.166.0 ou versão compatível iniciadas pelo wrapper. Conversas do Codex Desktop/host e tarefas fora dele não são observadas pelo ledger CLI. O fluxo JSONL não informa o nome/hash do agente carregado; por isso `profile_identity_verified` é sempre `false`. `agent_spawn_calls` conta início de chamada; `agent_spawn_completed` conta chamada concluída; `agent_spawn_failures` conta falha explicitamente observada; `agent_dispatches_observed` conta conclusão com identificador receptor, sem persistir esse identificador. Isso não prova qual perfil foi carregado.

O host nativo e o adaptador CLI são rotas diferentes. Um smoke nativo de `intake-normalizer` foi observado em 2026-11-06: a ferramenta recebeu o `agent_type` nomeado, iniciou uma sessão filha e retornou intake estruturado. O agente não conseguiu confirmar identidade/hash do TOML efetivamente carregado; essa evidência demonstra apenas despacho nomeado pelo host e comportamento compatível nesta sessão, não identidade versionada nem execução pelo CLI. Veja [o registro do smoke](../docs/evaluations/runtime-smoke-2026-11-06.md). Não infira telemetria Desktop a partir de `codex_runs.jsonl`.

No CLI, o primeiro smoke completou um turno em 17,452 s (51.534 tokens de entrada, 217 de saída), mas a resposta reportou falha ao carregar contexto da delegação e a métrica teve `agent_spawn_calls=0`. Após habilitar `[features].multi_agent` no projeto, ativar `--enable multi_agent` e ignorar config global, o segundo smoke completou em 10,906 s (54.457 tokens de entrada, 129 de saída), sem eventos de colaboração nem chamadas de spawn. Um terceiro smoke, com papéis também registrados via argumentos CLI `-c`, completou em 14,494 s (109.565 tokens de entrada, 159 de saída). O registro minimizado observou `collaboration_tool_calls=1`, mas `agent_spawn_calls=0`, `agent_dispatches_observed=0` e `profile_identity_verified=false`. A resposta foi o marcador sintético esperado, porém o evento não identifica qual operação de colaboração ocorreu nem um perfil/receptor; portanto não prova spawn, dispatch ou carregamento do `intake-normalizer`. A issue upstream [#14579](https://github.com/openai/codex/issues/14579) documenta problema de registry de papéis locais na CLI 0.114.0 e relata `-c` como controle positivo; ela não confirma que esse defeito exista na CLI 0.166.0 usada aqui. O registro via `-c` é um workaround plausível ainda sem comprovação comportamental específica. As três execuções usaram prompts diferentes; não permitem inferir efeito causal nem redução de tokens. A orquestração nativa do host é avaliada separadamente do CLI e não altera estes registros.

Exemplo de tarefa sintética em modo somente leitura (o prompt não é colocado na linha de comando):

```sh
printf '%s\n' 'Resuma este pedido: corrigir a validação de um campo.' | \
  python3 scripts/codex_runtime_capture.py --task-size small
```

Para uma tarefa de código que já foi autorizada, habilite escrita explicitamente e ajuste o limite, se necessário:

```sh
python3 scripts/codex_runtime_capture.py --task-size medium \
  --sandbox workspace-write --timeout-seconds 900
```

O timeout padrão é 15 minutos e o limite configurável é 30 minutos; ao expirar, o processo Codex e seus filhos são terminados e só métricas parciais minimizadas podem ser guardadas. `--ephemeral` evita persistência de histórico pelo CLI. `max_goal_token_budget=10000` limita apenas objetos Goals quando usados; não impõe teto geral de tokens por execução. O runtime 0.166.0 não expõe neste wrapper um limite total confiável por tarefa; tokens ficam registrados quando o evento os fornece.

Os registros não incluem custo em dinheiro, identidade de perfil nem conteúdo de execução. A análise existente de [`schemas/ledger.schema.json`](../schemas/ledger.schema.json) continua separada e exige export manual minimizado; não trate o relatório de processo como se fosse análise de runtime.

O contrato aceita uma linha JSON por evento. Campos técnicos opcionais incluem duração/custo somente quando medidos pelo runtime, código enumerado de falha e contagens de findings/reaberturas. Tarefa e checks usam identificadores restritos; o analisador rejeita texto livre e chaves fora da lista. Valores desconhecidos ficam `null` quando o contrato permitir; nunca estime tokens, custo ou duração.

Para analisar um arquivo previamente minimizado e autorizado:

```sh
python3 scripts/analyze_traces.py logs/export-minimized.jsonl
```

O resumo agrega contagens e médias, não repete identificadores, e gera no máximo duas propostas descritivas. Não conclui causalidade, não invoca agentes, não altera TOML, não promove regras e não pontua maturidade. O validador falha diante de campos inesperados, timestamps inválidos e valores sensíveis reconhecidos; isso reduz exposição, mas não substitui revisão de privacidade antes da exportação.

## Caminho para ampliar cobertura

Para provar comportamento e ampliar o piloto além do CLI, ainda são necessários uma API/evento de execução que identifique o perfil carregado e hashes confiáveis, além de política aprovada de acesso, retenção e minimização. A integração futura deverá:

1. observar perfil e versão/hash carregados, execução e resultado sem inferir identidade pelo TOML instalado;
2. transformar eventos numa allowlist do ledger antes de persistir, descartando texto bruto no ponto de coleta;
3. validar cada evento contra o schema, limitar volume/retenção e rejeitar por padrão formatos/campos novos;
4. separar credenciais e permissões de leitura das ferramentas de escrita/ação; o coletor não recebe capacidade de mudar agentes;
5. ter testes de privacidade, carga, duplicação/retry e regressão, além de uma rota de desligamento e retenção verificável;
6. rodar primeiro em modo shadow, comparar cobertura/erros com o export manual e só declarar métricas operacionais após baseline representativa e corpus autorizado.

O smoke nativo demonstra uma execução comportamental por nome nesta sessão, mas não resolve identidade/hash do arquivo instalado nem coleta de eventos do Desktop. O adaptador CLI também segue sem despacho identificado. `eval/MANIFEST.json` e `scripts/eval_run.py --dry-run` mantêm avaliações de identidade/hash como N/A/PENDING; as métricas do CLI são instrumentação parcial e não reduzem esses gaps.
