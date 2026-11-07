# Runtime smoke — 2026-11-06

## Execução nativa do host Codex

- **Objetivo:** verificar se uma sessão nativa do host consegue despachar o papel `intake-normalizer` para um seed simples.
- **Entrada sintética:** `renomear botão Salvar para Enviar`.
- **Ação observada:** chamada da ferramenta `collaboration.spawn_agent` com `agent_type="intake-normalizer"` e `fork_turns="none"`; o retorno do host identificou a sessão filha `/root/native_role_smoke`.
- **Resultado:** o subagente devolveu um objeto de intake com objetivo, lacunas, premissas e perguntas mínimas. Nenhum arquivo foi alterado.
- **Conclusão permitida:** o host nativo desta sessão executou despacho por nome e retornou conteúdo compatível com o papel esperado.
- **Limitações:** a resposta do agente declarou que não tinha identidade de perfil disponível. Esta chamada não prova hash/conteúdo do TOML instalado, não demonstra cobertura em outras sessões e não fornece telemetria confiável de tokens/custo. A saída completa não é armazenada aqui.

## Execução pelo adaptador Codex CLI

O terceiro smoke CLI, feito com o wrapper `scripts/codex_runtime_capture.py` e a CLI `0.166.0`, é independente do smoke nativo acima:

| Medida | Resultado observado |
|---|---:|
| `collaboration_tool_calls` | 1 |
| `agent_spawn_calls` | 0 |
| `agent_dispatches_observed` | 0 |
| `profile_identity_verified` | `false` |
| Tokens de entrada/saída | 109.565 / 159 |
| Duração | 14,494 s |

O marcador sintético retornado pelo turno não identifica qual operação de colaboração ocorreu, nem prova que um filho foi iniciado. O evento não expôs receptor ou identidade de perfil. Assim, o adaptador CLI segue sem demonstração de dispatch e não deve ser usado para alegar observabilidade do Codex Desktop/host.

## Estado de avaliação

| Capacidade | Estado | Evidência/lacuna |
|---|---|---|
| Dispatch nativo por nome nesta sessão | `OBSERVADO` | Ferramenta recebeu `agent_type=intake-normalizer` e houve retorno de sessão filha. |
| Saída compatível com intake | `OBSERVADO` | A resposta continha objetivo, lacunas e premissas. |
| Hash/versão do perfil carregado | `PENDING` | Nenhuma identidade/hash confiável foi exposta pelo runtime ou confirmada pelo agente. |
| Dispatch pelo wrapper CLI | `PENDING` | O smoke CLI não observou `spawn_agent` nem receptor. |
| Telemetria do Codex Desktop/host | `N/A` | O logger atual consome apenas JSONL de `codex exec`; não foi coletado trace do host. |

Este smoke é evidência pontual, não baseline, avaliação repetida ou prova de autonomia geral. Não atribua a ele redução de tokens nem resultado para outros perfis ou classes de tarefa.
