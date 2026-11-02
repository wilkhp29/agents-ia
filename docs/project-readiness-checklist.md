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

## Regra de remediação

1. Faça a auditoria antes de apresentar o plano de implementação; continue a descoberta se a árvore, stack ou destino de integração estiverem ambíguos.
2. Diferencie bloqueio desta tarefa de melhoria adjacente. Inclua no mesmo plano apenas lacunas que impedem ou enfraquecem diretamente os critérios aprovados, como um teste de regressão necessário ou um CI básico inexistente.
3. Identifique arquivo, especialista, critério verificável, verificação e rollback para cada correção local. A aprovação explícita do plano cobre os itens enumerados; não peça confirmação repetida para passos reversíveis já aprovados.
4. Não altere lacunas não relacionadas. Registre-as como backlog com impacto e responsável sugerido.
5. Permissões, branch protection/rulesets remotos, segredos, compra, gasto, publicação, deploy, mudanças em produção e compartilhamento de dados precisam constar com alvo e efeito exatos no plano e ter autorização explícita. Não alegue que instruções de prompt bloqueiam tecnicamente uma ferramenta.
6. Após a remediação, entregue a matriz atualizada com evidência real. `product-qa` verifica o diff e as correções que pertencem ao escopo; um item N/A ou fora de escopo não deve ser falsamente marcado como resolvido.

## Registro compacto

```text
Área | Status | Evidência | Relevante ao pedido? | Responsável | Ação/critério | Verificação/resultado
```

Não copie segredos ou dados pessoais para a matriz. Use caminhos de arquivo, nomes de ferramentas e resultados minimizados.
