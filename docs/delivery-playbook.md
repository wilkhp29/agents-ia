# Fluxo de entrega de produto digital

Este playbook complementa as instruções de `product-lead`, a [auditoria de prontidão](project-readiness-checklist.md) e os casos de [avaliação dos agentes](evaluations/agent-workflow-v1.md). Ele é um roteiro adaptável: cada projeto verifica o que existe e seleciona os controles pertinentes à sua stack, risco e ambiente.

## Etapas e gates

| Etapa | Owner | Saída verificável | Gate |
|---|---|---|---|
| Descoberta | `product-lead`, com `product-manager`/pesquisa se necessário | problema, usuário, objetivo mensurável, fatos/hipóteses, escopo e decisões pendentes | não implementar durante discussão; apresentar plano e obter autorização explícita |
| Especificação | `product-lead`; `product-designer`, `software-architect`, domínio/segurança conforme necessidade | brief, critérios `AC-*`, estados/contratos, exclusões, riscos, verificações, owner e rollback aplicável | usar EGM só quando há decisões materiais de produto/UX/arquitetura; incorporar uma revisão na pergunta de aprovação existente |
| Prontidão | `product-lead` com especialistas aplicáveis | matriz presente/ausente/N/A/decisão necessária, evidência, relevância, owner e ação | lacunas necessárias entram explicitamente no plano; lacunas adjacentes ficam no backlog |
| Implementação | `software-engineer` | feature branch Git Flow, diff focado, comandos reais, resultados por critério, risco e SHA | implementar somente escopo aprovado; verificações iniciais direcionadas e conjunto final conforme risco |
| Revisão de entrega | `product-lead` e terminal `product-qa` | snapshot identificado, diff completo, critérios, traces/saídas e matriz de achados | QA avalia o diff atual; `FAIL` volta ao engenheiro; somente `PASS` libera PR |
| PR e CI | `product-lead` publica; CI valida; humano revisa/mescla | PR para `develop`, checks requeridos e descrição com SHAs/evidências | branch protection/checks são confirmados no provedor; agente não faz merge |
| Release e operação | `devops-sre`, owner humano do serviço | artefato/commit, ambiente, aprovação, smoke/health, sinais/limites, janela, plano de rollback e owner | produção/release/deploy exigem autorização específica; promova o mesmo artefato validado |
| Aprendizado | `data-analyst`/`devops-sre`, `product-lead` integra | métricas da tarefa e pós-release, gaps e regressões propostas | adicione a avaliação somente dados minimizados/autorizados; estabeleça baseline antes de metas |

## EGM opcional na especificação

Para feature de porte médio/grande ou com decisão de produto, experiência ou arquitetura, o `product-lead` pode usar o plugin [Elephant Goldfish Model](https://github.com/google/elephant-goldfish-model): brainstorm, draft e review. O artefato aprovado pode ser guardado em `docs/designs/`. Goldfish procura premissas ausentes, ambiguidades, edge cases e riscos antes de engenharia. Mudanças pequenas e bem especificadas podem pular este passo.

EGM não substitui aprovação humana, teste, revisão de código ou `product-qa`. Consolide o resultado na mesma especificação/plano e faça uma única pergunta de autorização de implementação, sem criar um segundo gate humano para o mesmo escopo. Escolha quais observações incorporar e registre as rejeitadas com motivo quando forem relevantes.

O upstream lista Codex como harness compatível e indica instalar o plugin completo:

```bash
codex plugin marketplace add google/elephant-goldfish-model
codex plugin add egm@egm
```

Após instalação, inicie uma nova sessão e confirme que as skills aparecem. Estes comandos seguem o marketplace upstream e não fixam uma revisão; confira origem, conteúdo, versão e compatibilidade antes de instalar em cada computador. **Este pacote não instala o plugin no `CODEX_HOME` do usuário.**

No Codex, o repositório upstream documenta dispatch nativo de subagentes, sem personas nomeadas do plugin, com fallback para subagente geral que lê a persona do Goldfish. Contexto novo isola turnos da conversa conforme o host, mas não prova que arquivos `AGENTS.md` locais/globais foram omitidos. Informe aos revisores os critérios e fontes que devem desafiar; não descreva a revisão como cega ou totalmente independente sem evidência do host. Verifique o guia upstream de [harnesses e limitações](https://github.com/google/elephant-goldfish-model/blob/main/docs/harnesses.md) antes de atualizar a integração.

Use drift report depois de mudança material na arquitetura/contrato e periodicamente quando a equipe mantiver muitas especificações; não agende em toda correção simples. Humano decide se o documento ou o código deve ser atualizado.

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

Antes de planejar a entrega, `devops-sre`/`software-engineer` verificam comandos realmente existentes e estado do pipeline. O PR inclui os checks necessários para os critérios: teste unitário/integrado, lint/tipos/build, segurança/dependências e contrato de artefato conforme aplicável. Para produtos com runtime, o plano do serviço registra:

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
