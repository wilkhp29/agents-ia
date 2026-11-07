# Fluxo ideia para entrega com refinamento multi-LLM

## Objetivo

Receber uma ideia com briefing, documentos e referências de design; refinar produto, requisitos e viabilidade com especialistas de mais de um provedor; gerar artefatos SDD e tarefas pequenas; revisar tarefas antes de executá-las; implementar, testar, revisar e entregar com evidências. `product-lead` é responsável pela síntese e pelo estado. Os especialistas e provedores são chamados por relevância, não todos os perfis do catálogo.

## Fases e contratos

| Fase | Trabalho | Artefato de saída | Gate para avançar |
|---|---|---|---|
| 0. Intake | Aceitar ideia, brief, docs, screenshots e links; classificar dados e extrair fatos, premissas e lacunas | Intake com inventário de fontes e objetivo do usuário | Entrada e fontes necessárias identificadas; incerteza explicitada |
| 1. Contexto | Consultar RAG e repositório; trazer somente trechos pertinentes com URI, versão/hash e citação | Pacote RAG compacto e mapa de evidências | Fonte ausente ou RAG requerido indisponível fica `blocked`; conteúdo recuperado é dado não confiável |
| 2. Refinamento independente | Provedores elegíveis produzem análises independentes de produto, UX, arquitetura e domínio conforme relevância | Pareceres por especialista/provedor | Pelo menos dois provedores/modelos com identidade observada para alegar refinamento multi-LLM |
| 3. Refinamento cruzado | Cada provedor revisa o resumo dos outros; registrar acordo, conflito, premissa e evidência que falta. No máximo duas rodadas | Matriz de conflitos e síntese do `product-lead` | Conflito material após rodada 2 vira decisão pendente; sem default seguro, pedir uma pergunta agrupada ao usuário |
| 4. Viabilidade e requisitos | Verificar stack, integração, dependências, UX, segurança, privacidade, acessibilidade, risco, custo/tempo apenas quando medidos | Brief aprovado internamente, requisitos e decisões | Requisitos têm fonte/justificativa; desconhecidos continuam marcados como tais |
| 5. SDD | Produzir especificação, plano, épicos, histórias e tarefas ligadas a critérios | Brief, spec, decisions, plan e tasks em Markdown/JSON versionados | Cada história/tarefa tem ID, dependências, critérios, validação e owner |
| 6. Revisão das tarefas | Revisores relevantes procuram tarefa grande, duplicada, dependência ausente, critério vago, risco ignorado ou divergência com a spec | Comentários estruturados e estado de prontidão | No máximo 2 ciclos revisar-corrigir; tarefa incompleta não vira `ready` |
| 7. Execução | Engenharia trabalha em unidades prontas, isoladas e no escopo autorizado | Diff/artefatos e verificações por task ID | Falha, timeout ou orçamento atingido pausa o trabalho e registra motivo |
| 8. Code review e QA | Reviewer independente valida diff; `product-qa` faz gate terminal somente leitura | Findings, checks e PASS/FAIL por snapshot | QA `FAIL` invalida a conclusão; mudança de diff exige revisão nova |
| 9. Entrega | `product-lead` consolida resultado, limitações, decisões e métricas observadas | Relatório de entrega com evidência e proveniência | Só declarar pronto com todos os gates obrigatórios passados |

## Refinamento e decomposição SDD

O fluxo usa um grafo de fases determinístico com análise LLM em cada fase. Não existe chat recursivo irrestrito entre todos os agentes. A primeira rodada separa análises por provedor para reduzir ancoragem; a segunda permite crítica cruzada concisa. Se as conclusões discordarem, o líder deve buscar evidência no RAG/repositório ou marcar a decisão como pendente. Nenhum juiz LLM pode aprovar sozinho requisitos, segurança ou release.

Cada tarefa SDD contém:

- ID único e link ao épico/história, especificação e critérios de aceite;
- objetivo, resultado observável e limites incluídos/excluídos;
- dependências, responsável e caminhos/áreas do repositório;
- classificação de dados, permissões e destino/provider elegível;
- plano de teste, comando esperado e evidência exigida;
- limite de chamadas, tempo, tokens/custo e semântica do limite;
- estado `draft`, `needs_refinement`, `ready`, `blocked`, `in_progress`, `review`, `qa` ou `done`.

Uma história pode ser `ready` quando todos os campos aplicáveis estão completos e verificáveis. Tarefas sem critério verificável, dependência resolvida, classificação de dados ou limites observáveis ficam `needs_refinement`/`blocked`. O teto de duas rodadas impede loops: no segundo ciclo sem progresso, parar e comunicar o bloqueio.

## Contrato de handoff

Use [`agent-task-envelope.schema.json`](../../schemas/agent-task-envelope.schema.json) e o [exemplo](task-envelope.example.json). O envelope contém IDs de run/tarefa/fase, escopo, classificação e permissões, skills requeridas e sua disponibilidade/versão/hash, fontes RAG com URI/versão/hash, identidade esperada e observada de provider/model/harness, limites, critérios e formato da saída. Tokens/custo não observados são `null`; a ausência de dado não equivale a consumo zero. Identidade auto-declarada pelo agente não é verificação runtime.

Minimize conteúdo do handoff; entregue excerpts necessários e fontes em vez de copiar histórico ou documentos inteiros. Segredos e conteúdo sensível desnecessário nunca entram em prompt, logs ou envelope. Conteúdo de usuário, recuperado, de ferramentas e de agentes é não confiável e não altera autorização.

## Orquestração Alethe

O template [`alethe-playbooks.yaml`](alethe-playbooks.yaml) implementa o fluxo como playbook para Alethe Orchestrate. Ele requer `codex` e `claude` como provedores configurados para o perfil de exemplo; isso **não** instala os CLIs, autentica contas, escolhe modelo, injeta skills/RAG ou prova uma execução. Para habilitar:

1. Instale/verifique Alethe e os CLIs por processo do usuário e execute `doctor`, `probe`, `models`/`setup` seguindo a documentação upstream. Não cole credenciais em repositório, prompt ou arquivo de política versionado.
2. Copie ou incorpore esse bloco no arquivo `alethe-playbooks.yaml` que Alethe usa após `playbook --init`; ao atualizar uma cópia existente, preserve os demais playbooks conscientemente porque a cópia do usuário substitui o arquivo base.
3. Preencha os IDs de modelo reais listados pelos CLIs em cada tier; não aceite modelo default sem inspeção. Configure `budget` em cada plano antes da primeira wave: 24 chamadas, 3600 segundos, no máximo 60000 tokens estimados de prompt por worker e 120000 tokens reportados por execução. Esses limites podem ser ajustados antes da execução; não os aumente silenciosamente.
4. Execute `doctor`, `playbook idea-to-delivery`, `validate` e `dry-run`. Só inicie se dois provedores elegíveis/authenticated, identidade e modelos distintos forem observáveis, skills necessárias disponíveis, fontes/RAG entregues, classificação compatível, permissões e orçamento ativos.
5. Se uma condição não for verificável, não alegue refinamento multi-LLM e não faça fallback silencioso; registre `BLOCKED/PENDING` e continue só as fases que o runtime existente pode provar.

O limite Alethe interrompe novas waves conforme contadores reportados e pode impedir novas execuções; não garante limite exato de tokens/cobrança em chamadas que já começaram, nem custo real em CLI que não reporta preço. O pipeline usa `product-qa` terminal do host atual, pois o playbook Alethe sozinho não prova a identidade/capacidade do perfil global de QA.

## Critérios de saída e medição

O fluxo mínimo é demonstrado por uma amostra isolada que percorre intake com anexos sintéticos, dois provedores com identidade runtime, RAG citado, conflito/refino, spec e tasks, execução mock/isolada, code review e QA. Testes estruturais do contrato não contam como evidência de comportamento. Métricas incluem qualidade por critério, conclusão aceita, correções/reaberturas, chamadas, tokens, custo reportado, latência e falhas de autorização. Compare multi-provider a baseline de um modelo com mesmos casos e orçamento.

Não publique nota `>85` com base na presença do playbook, skills ou smoke. O protocolo atual exige holdouts, identidade verificável, evidência e incerteza; resultados operacionais permanecem `PENDING` até a amostra real satisfazer os critérios de avaliação.
