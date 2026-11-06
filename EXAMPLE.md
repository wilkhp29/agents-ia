# Exemplo de fluxo: produto digital

Este cenário é fictício e ilustra handoffs, aprovações e evidências; não é pesquisa de mercado.

## 1. Início com o líder

**Usuário:** “Quero criar um app de finanças pessoais.”

**product-lead:** conduz descoberta do `sdd-layout-ecc`: quem usará, problema, alternativa atual, sinal de sucesso e fora de escopo. Não presume público, plataforma, funcionalidades ou monetização. Registra perguntas que mudam o escopo e prepara critérios verificáveis.

Antes do plano, audita o repositório alvo: instruções/stack; estado e destino Git Flow; testes/build/lint e CI; segurança/QA; e release/observabilidade se houver runtime. Para cada área informa `PRESENTE`, `AUSENTE`, `N/A` ou `DECISÃO NECESSÁRIA`, com evidência e responsável. Lacunas diretamente necessárias entram no mesmo plano aprovado; itens sem relação ficam como backlog.

## 2. Definição de produto

`product-manager` organiza problema, MVP, critérios `DADO/QUANDO/ENTÃO` com IDs (`AC-1`, `AC-2`), estados de erro relevantes e decisões abertas. Marca como hipótese qualquer ideia não confirmada.

## 3. Pesquisa de mercado

O líder pode encaminhar ao `deep-researcher` uma pergunta, segmento, geografia e período aprovados. O agente traz fontes, data, metodologia, alternativas e lacunas. Não trata hipóteses como validação de demanda nem inicia contato com usuários sem autorização.

## 4. Arquitetura, plano e aprovação

O líder classifica o esforço e escolhe o menor fluxo que preserva os gates: uma correção pequena recebe critérios curtos e somente o especialista necessário; esta feature de finanças recebe SDD completo, porque domínio, privacidade e segurança mudam as decisões. Após critérios aprovados, `software-architect` compara opções conforme equipe, orçamento e ambiente. O líder apresenta plano ligado aos critérios e explicita escopo, verificações e gates. A aprovação do plano pode autorizar implementação dentro desse escopo; uma aprovação anterior de pesquisa não autoriza desenvolvimento. Passos reversíveis cobertos pelo plano não pedem confirmação repetida. Mudanças de escopo, risco, custo ou acesso a dados voltam ao usuário.

## 5. Design da experiência

Quando houver interface, `product-designer` detalha tarefa, hierarquia, fluxo, estados e responsividade; prepara contrato visual e critérios observáveis. A interface só é implementada após aprovação desse contrato ou confirmação explícita de que ele está incluído no plano aprovado.

## 6. Implementação e revisão

`software-engineer` consulta a base de conhecimento disponível e segue Git Flow. Usa `develop` como base de `feature/*`; se `develop` não existir, cria-a localmente a partir da linha primária (`main` ou `master`) que preserva a integração. Em caso de histórico, upstream ou alterações locais ambíguas, preserva o estado e consulta o líder.

O handoff para engenharia segue [schemas/handoff.schema.json](schemas/handoff.schema.json):

```json
{
  "goal": "Propor um MVP para finanças pessoais",
  "phase": "implementação",
  "owner": "software-engineer",
  "criteria": ["AC-1: usuário registra uma despesa"],
  "decisions": ["MVP local; sem sincronização bancária"],
  "out_of_scope": ["Conexão com bancos"],
  "risks": ["Dados financeiros pessoais"],
  "paths": ["src/expenses/"],
  "evidence": ["Plano aprovado pelo usuário"],
  "gaps": ["Stack do projeto ainda não auditada"],
  "next": "Auditar projeto e implementar dentro do escopo aprovado"
}
```

Subtarefas independentes de pesquisa podem ocorrer em paralelo; implementação dependente de arquitetura espera sua decisão. O engenheiro roda primeiro a verificação rápida da área alterada e depois todas as checagens obrigatórias antes da entrega. Ao concluir, informa SHA-base, HEAD, arquivos, critérios cobertos, comandos/exit codes, riscos e lacunas, sem repetir em prosa o conteúdo do diff.

Se a auditoria apontar um teste ou CI local ausente que impeça comprovar os critérios aprovados, o plano inclui sua criação e o engenheiro a implementa nessa mesma branch. Regras remotas, secrets, publicação, deploy ou acesso a produção são descritos como decisão/ação externa separada e só ocorrem com autorização explícita.

O líder envia diff atualizado e snapshot ao `product-qa` somente leitura. QA registra uma linha por critério: `critério | resultado | evidência | verificação`. Registra SHA/diff revisado, ferramentas ou skills indisponíveis e lacunas. Em `FAIL`, o engenheiro corrige e apresenta novo diff e evidências; QA revisa o estado novo. Não se reutiliza um PASS de snapshot anterior.

## 7. Aquisição

`product-growth` pode propor conteúdo, SEO e experimento pago com métricas e orçamento. Criar/publicar campanhas ou gastar exige aprovação humana explícita imediatamente antes da ação.

## 8. Métricas e governança

`data-analyst` define eventos, fórmulas, funis e qualidade; separa observações de hipóteses e aponta limites de privacidade. `governance-specialist` identifica riscos, responsáveis, controles, avaliações e questões que precisam de decisão humana. Nenhum certifica conformidade ou acessa dados sem autorização. O líder reúne os resultados paralelos, verifica contradições e mantém ownership da decisão integrada.

## 9. Operação, documentação e domínio

Antes do lançamento, `devops-sre` audita pipeline e recuperação, propõe deploy/rollback, SLOs, alertas, runbooks, limites de custo e resposta a falhas; publica ou altera produção só com aprovação explícita. Em biblioteca ou pacote sem runtime, deploy é `N/A`; valide artefato/instalação e rollback próprios do pacote. `documentation-support` baseia conteúdo em comportamento confirmado. `domain-specialist` declara domínio e jurisdição, cita fontes/versões, registra incertezas e encaminha decisões profissionais a pessoas qualificadas.

## 10. Fechamento e melhoria do processo

O líder só encerra com critérios e gates aplicáveis evidenciados, pendências e itens fora de escopo declarados. Cada evento no ledger segue [schemas/ledger.schema.json](schemas/ledger.schema.json), uma linha JSON append-only por evento. Registre somente classe, agentes, tentativas, nomes/resultado de checks e tokens se o runtime os fornecer; não inclua prompts brutos, PII, segredos ou saídas completas de ferramentas. Mede baseline antes de estabelecer metas; não estima dados ausentes nem pontua indivíduos. Uma nota de 0–100 só é operacional depois de avaliação versionada, fórmula publicada, amostra representativa e incerteza declarada.

Exemplo de evento minimizado:

```json
{"task":"task-2026-001","class":"A","agent":"software-engineer","attempts":1,"tests":["unit_suite"],"judge":"pending","human":"none","tokens_in":null,"tokens_out":null,"ts":"2026-11-06T12:00:00Z","duration_seconds":null,"cost_credits":null,"failure_code":"none","review_findings":0,"reopened":0}
```

## 11. Compra empresarial faturada

Para comprar mercadorias de qualquer categoria legal para revenda com boleto faturado, o líder encaminha `cnpj-boleto-buyer` com objetivo, empresa/CNPJ, itens ou parâmetros de busca, destino e limites. O agente pesquisa fornecedores, compara custo total e condições, verifica riscos e prepara localmente os campos/documentos de cadastro e o resumo do pedido. Como os perfis TOML não aplicam autorização determinística às ferramentas externas, a pessoa responsável confere as fontes e conclui pessoalmente cadastro e pedido. Produtos regulados/ilegais, compartilhamento não autorizado de documentos, crédito/garantia pessoal e pagamento de boleto são encaminhados para decisão humana; o agente nunca afirma que concluiu uma ação externa.

## 12. Bug bounty autorizado

Depois que o usuário aprova o plano, `product-lead` encaminha ao `hacking` a fonte oficial do programa, ativos explicitamente in-scope, exclusões, métodos, janela, taxa, contas de teste e critérios. O agente valida as regras vigentes antes de testar e monta uma matriz com hipóteses positivas/negativas, limites, estados de erro e sequências incomuns, indicando risco e evidência mínima. Se encontrar dados de terceiros, uma ambiguidade ou risco material, interrompe o caso e volta ao líder. DoS, brute force, phishing, persistência, evasão, alteração destrutiva, exfiltração/acesso a dados de terceiros e testes fora de escopo ficam proibidos. REA apoia reverse engineering e evidências, sem garantir detecção; o agente entrega um rascunho de relatório e não o submete. O `product-qa` continua independente se houver mudança de código/configuração.
