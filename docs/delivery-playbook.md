# Fluxo de entrega de produto digital

Este playbook complementa as instruções de `product-lead`, a [auditoria de prontidão](project-readiness-checklist.md) e os casos de [avaliação dos agentes](evaluations/agent-workflow-v1.md). Ele é um roteiro adaptável: cada projeto verifica o que existe e seleciona os controles pertinentes à sua stack, risco e ambiente.

## Etapas e gates

| Etapa | Owner | Saída verificável | Gate |
|---|---|---|---|
| Intake e descoberta | `intake-normalizer`, `product-lead`, especialistas/EGM conforme necessidade | seed normalizado, brief, lacunas, premissas e critérios | pedido explícito de implementação cobre decisões internas reversíveis; perguntar apenas por decisão que altere objetivo/aceite/risco sem default seguro |
| Especificação | `product-lead`; `product-designer`, `software-architect`, domínio/segurança conforme necessidade | brief, critérios `AC-*`, estados/contratos, exclusões, riscos, verificações, owner e rollback aplicável | usar EGM quando reduzir incerteza de produto/UX/arquitetura; incorporar achados sem gate duplicado |
| Prontidão | `product-lead` com especialistas aplicáveis | matriz presente/ausente/N/A/decisão necessária, evidência, relevância, owner e ação | lacunas necessárias entram explicitamente no plano; lacunas adjacentes ficam no backlog |
| Implementação | `software-engineer` | feature branch Git Flow, diff focado, comandos reais, resultados por critério, risco e SHA | pedido explícito de execução cobre trabalho local reversível necessário ao objetivo; perguntas só quando falta default seguro para objetivo/aceite/risco |
| Revisão de código e entrega | `code-reviewer`, depois `product-qa` terminal | snapshot identificado, diff completo, critérios, traces/saídas e achados | code review é independente; QA avalia diff atual; `FAIL` volta ao engenheiro; apenas QA `PASS` libera PR |
| PR e CI | `product-lead` publica; CI valida; humano revisa/mescla | PR para `develop`, checks requeridos e descrição com SHAs/evidências | branch protection/checks são confirmados no provedor; agente não faz merge |
| Release e operação | `devops-sre`, owner humano do serviço | artefato/commit, ambiente, aprovação, smoke/health, sinais/limites, janela, plano de rollback e owner | produção/release/deploy exigem autorização específica; promova o mesmo artefato validado |
| Aprendizado | `data-analyst`/`devops-sre`, `product-lead` integra | métricas da tarefa e pós-release, gaps e regressões propostas | adicione a avaliação somente dados minimizados/autorizados; estabeleça baseline antes de metas |

## Handoff e ledger estruturados

Todo handoff entre agentes deve ser um objeto JSON que valide contra [`schemas/handoff.schema.json`](../schemas/handoff.schema.json): objetivo, fase, responsável, critérios, decisões, exclusões, riscos, paths, evidências, lacunas e próximo passo. O schema valida formato e limites de tamanho; não representa aprovação nem concede permissão. Evite incluir prompt bruto, segredo, dado pessoal ou conteúdo completo de artefato quando uma referência local minimizada for suficiente.

Registre métricas como eventos JSONL conforme [`schemas/ledger.schema.json`](../schemas/ledger.schema.json), acrescentando linhas sem reescrever eventos anteriores. Guarde apenas identificadores de tarefa não pessoais, classe, agente, contagem de tentativas, códigos de checks/falhas, resultado do judge, interação humana e tokens/duração/custo/revisão somente quando a telemetria fornecer números confiáveis. Tokens ausentes são `null`; não estime métricas nem inclua transcript, PII, segredos ou saída de ferramenta. O validador do pacote suporta explicitamente o subconjunto de keywords JSON Schema usado nestes contratos, testa fixtures válidas/inválidas e falha se encontrar keyword de validação não suportada; não é um validador universal JSON Schema.


## Autonomia decidível e limites

`scripts/policy.py` calcula A/B/C e motivos a partir de sinais verificáveis para orientar o fluxo. É necessário fornecer ao menos um campo reconhecido: objeto vazio, chave desconhecida, estrutura inválida e sinais numéricos malformados vão para C. Um payload válido sem sinais de risco, por exemplo `{"paths": []}`, pode ir para A. A saída inclui `authorizes_action: false`: classe, YAML e instruções TOML não alteram permissões nem sandbox. Limites numéricos atuais estão marcados provisórios e não são calibrados. Timeout registra estado pendente, nunca consentimento. Ações fora do checkout, gastos, submissões, publicações, produção, deploy, release e merge continuam sujeitas à autorização específica aplicável.

Fallback é permitido apenas para trabalho de execução quando equivalente em competência; `code-reviewer` e `product-qa` não podem ser substituídos. Sem gate independente disponível, a tarefa permanece pendente. Limites de tentativas/tempo/custo são configurações provisórias; ao exceder, registre causa/evidência/próximo passo sem classificar todo bloqueio artificialmente como risco C.

O piloto CLI registra métricas minimizadas apenas para execuções iniciadas por `scripts/codex_runtime_capture.py`; o Codex Desktop e invocações fora do wrapper não são coletados. `.codex/config.toml` habilita `features.multi_agent` e declara papéis; o wrapper também passa suas descrições e caminhos validados em argumentos CLI `-c`, sem editar config global. `.codex/config.toml` limita concorrência a 3; `max_depth=1` vale para backend V1 e pode ser ignorado por V2. A issue upstream [#14579](https://github.com/openai/codex/issues/14579) documenta um problema de registry em CLI 0.114.0 e relata `-c` como controle positivo; a causa não está confirmada para CLI 0.166.0. Um terceiro smoke após esse workaround observou `collaboration_tool_calls=1`, porém zero `agent_spawn_calls`, zero `agent_dispatches_observed` e `profile_identity_verified=false` (109.565 tokens de entrada, 159 de saída, 14,494 s). Embora tenha retornado o marcador pedido, o registro não identifica a operação, receptor nem perfil; dispatch continua sem prova e não se pode atribuir causalidade ao workaround. Os três prompts diferem e não permitem concluir redução de tokens. O wrapper usa `--ephemeral`, não escreve eventos crus, aplica timeout real e grava métricas pelo schema runtime v2. `max_goal_token_budget=10000` é limite de Goals, não limite global por tarefa. Consulte [`logs/README.md`](../logs/README.md) para uso e restrições.

`scripts/analyze_traces.py` ainda resume somente ledger de processo minimizado exportado; métricas runtime têm schema separado. `eval/MANIFEST.json` registra que não havia corpus histórico autorizado com diffs de referência. `scripts/eval_run.py --dry-run` enumera E1–E8 como PENDING e não invoca perfis, compara diffs ou atribui score. `judge` e `judge-auditor` permanecem indisponíveis até rubricas e amostras autorizadas; `retro` só propõe mudanças. `scripts/promote.py` falha fechado enquanto não houver avaliação reproduzível; promoção automática segue desabilitada. Não há baseline de custo ou tokens; valores ausentes são N/A.

## EGM opcional na especificação

Para feature de porte médio/grande ou com incerteza relevante de produto, experiência ou arquitetura, o `product-lead` pode usar o plugin [Elephant Goldfish Model](https://github.com/google/elephant-goldfish-model): brainstorm, draft e review. O artefato e as premissas podem ser guardados em `docs/designs/`. Goldfish procura premissas ausentes, ambiguidades, edge cases e riscos antes de engenharia. Mudanças pequenas, claras e de baixo risco seguem fluxo curto sem swarm; paralelize só subtarefas independentes, respeitando o máximo configurado de três agentes concorrentes. EGM e paralelismo aumentam custo; use-os se o benefício esperado justificar chamadas extras.

EGM não substitui autorização exigida para efeitos externos, teste, revisão de código ou `product-qa`. Quando o pedido já autoriza implementação local, consolide os resultados no handoff sem gate humano duplicado. Escolha quais observações incorporar e registre as rejeitadas com motivo quando forem relevantes.

O plugin `egm@egm` foi instalado e verificado no Codex global na versão `0.1.0`, pelo marketplace `google/elephant-goldfish-model`, no commit upstream `0dfb5bf3eebd551d1e805c3ab16cbaa9b1c2c42a`. Para reproduzir em outro computador, instale o marketplace fixado nesse commit e o plugin completo:

```bash
codex plugin marketplace add google/elephant-goldfish-model --ref 0dfb5bf3eebd551d1e805c3ab16cbaa9b1c2c42a
codex plugin add egm@egm
```

Após a instalação, inicie uma sessão nova do Codex e confirme que as skills EGM estão disponíveis. O repositório inclui wrappers TOML nomeados em `agents/egm-*.toml`, instalados pelo mesmo `install-agents.sh`. Eles não embalam, copiam nem instalam o plugin no `CODEX_HOME`; a instalação do plugin e de suas skills é separada. Cada wrapper resolve a persona dentro do bundle EGM ativo/pinado, lê o arquivo Markdown de origem e deve reportar caminho relativo e versão/commit observado. Se houver zero ou múltiplas personas compatíveis, a revisão fica bloqueada. Para atualizar o pin, revise o diff upstream, confirme versão e compatibilidade com Codex, teste instalação e skills numa sessão nova e atualize este registro somente após essa revisão.

O EGM upstream não registra suas personas como subagentes nomeados no Codex. Este pacote define wrappers com nomes próprios (`egm-comprehension`, `egm-zoom-out`, `egm-design`, `egm-structural`, `egm-style`, `egm-implementation-readiness`, `egm-codebase-details`) compatíveis com o suporte do Codex a agentes personalizados TOML. O líder escolhe o nome do wrapper correspondente à análise e verifica a identidade efetivamente selecionada; o wrapper exige leitura da persona do bundle pinado e falha em vez de fingir que a carregou. Isso contorna a falta de nomes no adaptador EGM, mas não contorna a limitação de isolamento: contexto novo isola turnos de conversa conforme o host, porém não prova que arquivos `AGENTS.md` locais/globais foram omitidos. Wrappers herdam permissões da sessão e não criam sandbox ou acesso somente leitura técnico. Informe aos revisores os critérios e fontes que devem desafiar; não descreva revisão cega ou totalmente independente sem evidência do host. Verifique o guia upstream de [harnesses e limitações](https://github.com/google/elephant-goldfish-model/blob/main/docs/harnesses.md) e a [documentação de agentes personalizados do Codex](https://learn.chatgpt.com/docs/agent-configuration/subagents) antes de atualizar a integração.

### Avaliação de uso dos wrappers EGM

A validação estática do pacote confirma nomes, campos TOML, persona-alvo, pin e advertências de isolamento; ela não prova despacho em runtime. Para uma rodada comportamental, em conversa descartável, solicite ao `product-lead` uma revisão de especificação média e confirme no registro real: nome carregado pelo host, hash do wrapper observado, leitura da persona correspondente dentro do bundle com commit/versão, arquivo-alvo/fontes lidos, saída do subagente e limitações de contexto. Inclua também um marcador exclusivo do contexto pai para detectar possível vazamento, sem concluir que sua ausência prova isolamento absoluto. Se nome, hash ou leitura da persona não puderem ser observados, registre `PENDING`; nunca converta configuração presente em `PASS` de runtime.

Use drift report depois de mudança relevante na arquitetura/contrato e periodicamente quando a equipe mantiver muitas especificações; não agende em toda correção simples. Humano decide se o documento ou o código deve ser atualizado.

## Matriz de risco para readiness

| Sinal da mudança | Critérios/checks a incluir | Especialista/owner |
|---|---|---|
| Interface ou navegação | tarefa e estados; mobile/responsivo; acessibilidade; SEO quando aplicável; evidência visual em breakpoints para UI | `product-designer`, `product-qa` |
| Entrada externa, auth ou integração | trust boundaries, validação, autorização server-side, abuso, erros, timeout, idempotência e testes negativos | `software-engineer`, `security`/`governance-specialist`, `product-qa` |
| Dados pessoais ou domínio regulado | minimização, acesso, retenção, jurisdição, classificação e fonte/versionamento das regras | `governance-specialist`, `domain-specialist` |
| API, schema ou migração | compatibilidade entre versões, expansão/migração/contração, backup e rollback/roll-forward | `software-architect`, `software-engineer`, `devops-sre` |
| Serviço implantável | artefato imutável, staging, smoke, alertas, critérios de abort, rollout e retorno | `devops-sre` e owner de serviço |
| Documentação/pacote sem runtime | validação de links/instalação, versão, integridade, backup e restauração; deploy/produção = N/A justificado | owner do pacote e `product-qa` |

O `product-lead` registra critério, evidência observada, lacuna, responsável e decisão. Não transforma cada sugestão da matriz em requisito universal.

## CI, staging e recuperação

Antes de planejar a entrega, `devops-sre`/`software-engineer` verificam comandos realmente existentes e estado do pipeline. O workflow classifica paths e verifica marcador de classe no PR; em push pós-merge, apenas registra a classe porque o evento não prova vínculo com PR. O PR inclui checks necessários aos critérios: testes, lint/tipos/build, segurança/dependências e contrato do artefato conforme aplicável. Branch protection/ruleset exigindo PR e este check é configuração externa que deve ser verificada no provedor. Para produtos com runtime, o plano do serviço registra:

1. Commit e identidade do artefato validado em CI.
2. Deploy em staging e smoke/health checks que cobrem o caminho crítico.
3. Aprovação e owner da promoção; em mudança arriscada, canary/feature flag com grupo e limite.
4. Janela e sinais pós-deploy (erros, latência, dados, custo ou métrica de produto pertinente).
5. Critério de abort/rollback, comando/runbook e verificação de recuperação; migrações compatíveis ou plano roll-forward.

Operação real, credenciais, branch protections, publicação e deploy não são autorizados apenas por existir documentação ou workflow YAML; obtenha a aprovação exigida para o alvo e o efeito específicos. Para projeto não implantável, marque os passos de runtime como N/A e valide a distribuição/instalação apropriada.

## Métricas com denominador e owner

Comece com coleta observável autorizada, sem dados sensíveis e sem pontuar pessoas. Defina a janela e segmente por classe de risco e tipo de trabalho. Os owners indicam fontes reais e gaps; não estimam valores que o runtime não fornece.

| Medida | Fórmula/fonte | Owner | Uso |
|---|---|---|---|
| Lead time ativo e espera | duração por fase; timestamps do issue, PR e CI quando disponíveis | `data-analyst`/`product-lead` | localizar fila, esclarecimento e retrabalho |
| Aprovação inicial de QA | blocos com PASS na primeira revisão ÷ blocos revisados | `product-lead`/`product-qa` | encontrar especificações ou evidências fracas |
| Reabertura | achados reabertos ÷ achados resolvidos | `product-qa` | encontrar correções incompletas ou regressões |
| Cobertura de critério | critérios aplicáveis com evidência vigente ÷ critérios aplicáveis | `product-lead`/`product-qa` | rastreabilidade de entrega |
| Confiabilidade/espera de CI | checks green ÷ checks concluídos; duração por check e causa de falha | `devops-sre` | identificar flakiness, runner lento ou feedback tardio |
| Falha e recuperação pós-release | deploys que exigem rollback/hotfix ÷ deploys; tempo de recuperação | `devops-sre` | orientar rollout, recuperação e risco |
| Uso/custo de agentes | tarefas concluídas, tokens/custo/duração por tarefa quando o runtime medir | `data-analyst` | comparar classes e avaliar trade-offs; N/A sem telemetria |

Mensalmente, revise tendências e amostras, investigue mudanças e só então defina metas. Não compare runs de agente se versões de prompt, runtime, ferramentas, dificuldade ou dados mudaram sem registrar diferença. Para E1–E8, use as tarefas versionadas e repetições, mas trate a ausência de identidade verificável do perfil como `PENDING`.
