# Exemplo de fluxo: produto digital

Este cenário é fictício e ilustra handoffs, aprovações e evidências; não é pesquisa de mercado.

## 1. Início com o líder

**Usuário:** “Quero criar um app de finanças pessoais.”

**product-lead:** conduz descoberta do `sdd-layout-ecc`: quem usará, problema, alternativa atual, sinal de sucesso e fora de escopo. Não presume público, plataforma, funcionalidades ou monetização. Registra perguntas que mudam o escopo e prepara critérios verificáveis.

## 2. Definição de produto

`product-manager` organiza problema, MVP, critérios `DADO/QUANDO/ENTÃO` com IDs (`AC-1`, `AC-2`), estados de erro relevantes e decisões abertas. Marca como hipótese qualquer ideia não confirmada.

## 3. Pesquisa de mercado

O líder pode encaminhar ao `deep-researcher` uma pergunta, segmento, geografia e período aprovados. O agente traz fontes, data, metodologia, alternativas e lacunas. Não trata hipóteses como validação de demanda nem inicia contato com usuários sem autorização.

## 4. Arquitetura, plano e aprovação

Após critérios aprovados, `software-architect` compara opções conforme equipe, orçamento e ambiente. A recomendação inclui trade-offs e riscos. O líder apresenta plano ligado aos critérios e explicita escopo, verificações e gates. A aprovação do plano pode autorizar implementação dentro desse escopo; uma aprovação anterior de pesquisa não autoriza desenvolvimento. Passos reversíveis cobertos pelo plano não pedem confirmação repetida. Mudanças de escopo, risco, custo ou acesso a dados voltam ao usuário.

## 5. Design da experiência

Quando houver interface, `product-designer` detalha tarefa, hierarquia, fluxo, estados e responsividade; prepara contrato visual e critérios observáveis. A interface só é implementada após aprovação desse contrato ou confirmação explícita de que ele está incluído no plano aprovado.

## 6. Implementação e revisão

`software-engineer` consulta a base de conhecimento disponível e segue Git Flow. Usa `develop` como base de `feature/*`; se `develop` não existir, cria-a localmente a partir da linha primária (`main` ou `master`) que preserva a integração. Em caso de histórico, upstream ou alterações locais ambíguas, preserva o estado e consulta o líder.

O handoff para engenharia identifica objetivo/fase, responsável, critérios, decisões, fora de escopo, riscos, áreas esperadas, evidências e resultado esperado. Ao concluir, o engenheiro informa SHA-base, HEAD atual, arquivos alterados, critérios cobertos, comandos com resultados/exit codes e lacunas.

O líder envia diff atualizado e snapshot ao `product-qa` somente leitura. QA registra uma linha por critério: `critério | resultado | evidência | verificação`. Registra SHA/diff revisado, ferramentas ou skills indisponíveis e lacunas. Em `FAIL`, o engenheiro corrige e apresenta novo diff e evidências; QA revisa o estado novo. Não se reutiliza um PASS de snapshot anterior.

## 7. Aquisição

`product-growth` pode propor conteúdo, SEO e experimento pago com métricas e orçamento. Criar/publicar campanhas ou gastar exige aprovação humana explícita imediatamente antes da ação.

## 8. Métricas e governança

`data-analyst` define eventos, fórmulas, funis e qualidade; separa observações de hipóteses e aponta limites de privacidade. `governance-specialist` identifica riscos, responsáveis, controles, avaliações e questões que precisam de decisão humana. Nenhum certifica conformidade ou acessa dados sem autorização.

## 9. Operação, documentação e domínio

Antes do lançamento, `devops-sre` propõe deploy/rollback, SLOs, alertas, runbooks, limites de custo e resposta a falhas; publicar ou alterar produção exige aprovação explícita. `documentation-support` baseia conteúdo em comportamento confirmado. `domain-specialist` declara domínio e jurisdição, cita fontes/versões, registra incertezas e encaminha decisões profissionais a pessoas qualificadas.

## 10. Fechamento e melhoria do processo

O líder só encerra com critérios e gates aplicáveis evidenciados, pendências e itens fora de escopo declarados. Mensalmente, a equipe observa aprovação na primeira revisão, reabertura de achados, cobertura de evidências, rodadas de esclarecimento e tempo por fase. Mede baseline antes de estabelecer metas e usa os dados para melhorar o sistema, não pontuar indivíduos.
