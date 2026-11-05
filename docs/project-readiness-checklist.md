# Auditoria de prontidão de um projeto

Use esta matriz no início de cada pedido que altere código, configuração ou produto. É um diagnóstico do repositório em questão, não um modelo que obriga todos os projetos a usar a mesma stack ou implantar um serviço.

## Resultado da auditoria

Registre, para cada linha aplicável: **status** (`PRESENTE`, `AUSENTE`, `N/A` ou `DECISÃO NECESSÁRIA`), **evidência** (arquivo/comando/resultado), **relevância para o pedido**, **responsável** e **ação/critério**. Não marque como presente algo inferido de uma instrução sem verificar o projeto/runtime.

| Área | Verificação e evidência sugerida | Responsável por remediação local |
|---|---|---|
| Instruções e contexto | `AGENTS.md`, README, stack/versões, arquitetura e convenções existentes | `product-lead` coordena; especialista da área executa |
| Estado e Git Flow | `git status`, branch/base/upstream, `main`, `develop`, branches remotas, destino de PR e histórico | `product-lead`; `software-engineer` prepara branches; remoto exige autorização |
| Validação | scripts reais de testes, build, lint, tipos e smoke checks; execute só o que é seguro e pertinente | `software-engineer` |
| CI e integração | workflows existentes, permissões do token, checks de PR, estado dos checks no provedor | `software-engineer` para YAML/código; `devops-sre` para pipeline/operação; regras remotas exigem autorização |
| Segurança e dependências | instruções de segurança, scanners/dependency lockfiles, dados/segredos e superfícies tocadas; declare cobertura e gaps | `software-engineer`, `governance-specialist` ou `product-qa` conforme risco |
| QA independente | agente/revisor terminal disponível, critérios, diff e evidências do snapshot atual | `product-lead` encaminha; `product-qa` revisa, não implementa |
| Release e recuperação | runtime implantável, ambientes, artefato/versionamento, smoke/health, rollback/backups, dono/alertas | `devops-sre`; marque N/A para documentação, bibliotecas e pacotes sem runtime |
| Observabilidade e custo | fontes autorizadas para tempo, erros, latência/custo, retenção e acesso; marque N/A quando não houver runtime | `data-analyst` e `devops-sre` conforme aplicável |
| Produto, UX e acessibilidade | tarefa/persona afetada, estados principais/erro/vazio e critério de acessibilidade para interface; `N/A` documentado para mudança sem interface | `product-manager` e `product-designer`; `product-qa` verifica UI |
| Dados e contratos | classificação/retensão, autorização, schema/API, compatibilidade, migração e plano de retorno quando persistência/contrato for alterado | `software-architect`, `domain-specialist`/`governance-specialist` conforme domínio; `software-engineer` implementa |
| Especificação e premissas | brief e design revisados quando a feature tiver decisões materiais de produto/UX/arquitetura; EGM opcional se instalado e suportado; `N/A` justificado em correção simples | `product-lead` integra; usuário decide trade-offs |

## Regra de remediação

1. Faça a auditoria antes de apresentar o plano de implementação; continue a descoberta se a árvore, stack ou destino de integração estiverem ambíguos.
2. Diferencie bloqueio desta tarefa de melhoria adjacente. Inclua no mesmo plano apenas lacunas que impedem ou enfraquecem diretamente os critérios aprovados, como um teste de regressão necessário ou um CI básico inexistente.
3. Identifique arquivo, especialista, critério verificável, verificação e rollback para cada correção local. A aprovação explícita do plano cobre os itens enumerados; não peça confirmação repetida para passos reversíveis já aprovados.
4. Não altere lacunas não relacionadas. Registre-as como backlog com impacto e responsável sugerido.
5. Permissões, branch protection/rulesets remotos, segredos, compra, gasto, publicação, deploy, mudanças em produção e compartilhamento de dados precisam constar com alvo e efeito exatos no plano e ter autorização explícita. Não alegue que instruções de prompt bloqueiam tecnicamente uma ferramenta.
6. Após a remediação, entregue a matriz atualizada com evidência real. `product-qa` verifica o diff e as correções que pertencem ao escopo; um item N/A ou fora de escopo não deve ser falsamente marcado como resolvido.

## Seleção proporcional por risco

Classifique o risco pelo impacto, exposição e reversibilidade, e associe cada verificação a um critério e evidência. A tabela é um guia adaptável, não exige stack, ferramenta ou ambiente específico.

| Classe | Sinal típico | Evidência mínima a considerar | Owner típico |
|---|---|---|---|
| Baixo | mudança local, reversível, sem dado/contrato/interface nem efeito externo | teste direcionado/regressão, diff, checagem obrigatória do repositório e QA independente | `software-engineer`, depois `product-qa` |
| Médio | mudança em comportamento, UI, integração, API ou dados não sensíveis | critérios por estado, testes de integração, compatibilidade; acessibilidade para UI; revisão de auth/entrada/sinks; smoke/rollback se implantável | especialista de implementação + `product-qa`; `devops-sre` quando houver runtime |
| Alto | dados sensíveis, autorização, domínio regulado, ação externa, migração arriscada ou produção | análise de ameaça/dados, controle de autorização determinístico, rollback/roll-forward, teste de falha, validação independente especializada e gate humano | `product-lead` coordena `governance-specialist`/`domain-specialist`/`devops-sre` e `product-qa` |

Para cada linha usada, registre `critério | risco | check | evidência/saída | owner | resultado | rollback/recuperação`. `N/A` exige motivo verificável. A decisão de pular checks tem que estar explícita no plano aprovado e não pode remover QA independente, autorização humana ou política de segurança obrigatória.

## Saída e operação

Para um serviço implantável, o plano/PR registra qual commit gera o artefato, como ele será promovido por ambiente, quem aprova, quais smoke/health checks determinam sucesso, janela de observação, sinais de aborto, caminho e owner de rollback, migrações compatíveis e onde ficam logs/alertas. Para biblioteca/documentação/pacote sem runtime, marque deploy/produção `N/A` e valide publicação/instalação e recuperação próprias do artefato. Não faça deploy; autorização específica continua necessária.

Depois da integração, use eventos existentes e autorizados para medir tendência por classe de tarefa: lead time por fase, tamanho/idade de branch/PR, espera de revisão, falha e duração do CI, aprovação inicial do QA, reabertura, falha de mudança, rollback/hotfix e tempo de recuperação. Registre numerador, denominador, janela e fonte; não colete conteúdo sensível nem pontue indivíduos. Defina metas somente depois de formar baseline representativa.

## Registro compacto

```text
Área | Status | Evidência | Relevante ao pedido? | Responsável | Ação/critério | Verificação/resultado
```

Não copie segredos ou dados pessoais para a matriz. Use caminhos de arquivo, nomes de ferramentas e resultados minimizados.
