# Exemplo de fluxo: produto digital

Este cenário é fictício e serve apenas para mostrar como os handoffs podem funcionar.

## 1. Início com o líder

**Usuário:** “Quero criar um app de finanças pessoais.”

**product-lead:** conduz a descoberta do `sdd-layout-ecc`: quem usará, qual problema específico, alternativa atual, sinal verificável de sucesso e fora de escopo. Não assume público, plataforma, funcionalidades ou monetização. Registra perguntas pendentes e solicita aprovação dos critérios e limites antes do plano.

## 2. Definição de produto

Com autorização para detalhar a fase, `product-manager` organiza problema, MVP, critérios `DADO/QUANDO/ENTÃO`, estados de erro relevantes e decisões abertas. Ele marca como hipótese qualquer ideia não confirmada.

## 3. Pesquisa de mercado

O líder pode recomendar `deep-researcher`, fornecendo segmento/geografia/período e pergunta de pesquisa aprovados. O agente traz fontes, data, metodologia, alternativas e lacunas. O líder não trata hipóteses como validação de demanda nem inicia contato com usuários sem autorização.

## 4. Arquitetura e plano

Após critérios aprovados, `software-architect` compara opções de stack conforme equipe, orçamento e ambiente. A recomendação inclui trade-offs e riscos. O líder atualiza o plano, liga tarefas a critérios e aguarda aprovação explícita antes de implementar.

## 5. Design da experiência

Quando houver interface, `product-designer` detalha tarefa, hierarquia, fluxo, estados e responsividade; inspeciona a direção visual disponível e prepara contrato visual e critérios observáveis. O usuário aprova esse brief antes do início da implementação da UI.

## 6. Implementação e revisão

Com plano e contratos de UI aprovados, `software-engineer` consulta a base de conhecimento disponível sobre stack/fluxo/segurança, verifica as convenções Git do repositório e trabalha em uma branch `feature/*` baseada em `develop` quando compatível. Altera somente o escopo autorizado, executa verificações e entrega arquivos, comandos e saídas reais. O líder envia cada bloco ao `product-qa` em modo somente leitura. Em `FAIL`, o engenheiro corrige, atualiza o diff e reexecuta as verificações afetadas; o ciclo só avança com `PASS` ou termina como bloqueado segundo o limite de tentativas.

## 7. Aquisição

`product-growth` pode propor conteúdo, SEO e um experimento pago com orçamento e métricas como proposta. Criar/publicar campanhas e gastar ficam parados até aprovação humana explícita.

## 8. Métricas e governança

`data-analyst` define eventos, fórmulas, funis e verificações de qualidade; separa dados observados de hipóteses e aponta limites de privacidade. `governance-specialist` identifica riscos, responsáveis, controles, critérios de avaliação e questões que precisam de decisão humana ou revisão jurídica/compliance. Nenhum dos dois certifica conformidade nem acessa dados sem autorização.

## 9. Operação, documentação e domínio

Antes do lançamento, `devops-sre` propõe plano de deploy/rollback, SLOs, alertas, runbooks, limites de custo e resposta a falhas; publicar ou alterar produção depende de aprovação explícita. `documentation-support` prepara onboarding, ajuda e respostas a dúvidas frequentes com base no comportamento confirmado do produto, sem inventar funcionalidades. Para regras específicas, `domain-specialist` valida conceitos e regras no domínio e jurisdição informados, cita fontes/versões, registra incertezas e encaminha decisões profissionais a especialistas humanos qualificados.

## Critério de fechamento

O líder só resume como concluído quando critérios e gates aplicáveis têm evidência, reporta o que não foi verificado e identifica itens futuros fora do escopo atual.
