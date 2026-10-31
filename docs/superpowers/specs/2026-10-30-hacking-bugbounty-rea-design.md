# Agente Hacking para Bug Bounty com REA

**Status:** Em revisão pelo usuário
**Branch de trabalho:** `feature/hacking-bugbounty-rea`
**Base:** `bb3bde5`

## Objetivo
Adicionar à equipe o agente `hacking`, especialista em bug bounty autorizado, sob gestão do `product-lead`, com REA como ferramenta de apoio para reverse engineering e coleta de evidência.

## Problema e motivação
O usuário quer investigar programas bug bounty com autonomia, testar caminhos negativos e incomuns, descobrir vulnerabilidades válidas e preparar relatos que possam resultar em recompensa. O usuário espera que o agente explique riscos e peça aprovações necessárias, enquanto o `product-lead` gerencia o trabalho.

## Objetivos
- Criar o perfil global versionado `agents/hacking.toml` e integrar seu uso ao fluxo do `product-lead`.
- Autorizar autonomia operacional somente dentro do plano de avaliação e das regras publicadas do programa.
- Usar REA para inspecionar aplicações, bundles e observações de navegador/rede quando essa evidência for relevante.
- Fazer testes sistemáticos de caminhos de erro, limites, autenticação/autorização, estados, sequências incomuns e falhas, dentro do escopo e sem impacto proibido.
- Entregar achados com evidência reproduzível, impacto, confiança, passos seguros de reprodução, limitações e rascunho do relatório.

## Não objetivos
- Prometer que encontrará bugs ou que um relatório será aceito ou pago.
- Tratar REA como scanner autônomo de vulnerabilidades; a documentação descreve ferramentas de reverse engineering e observação, não uma garantia de detecção.
- Testar alvos fora do escopo, contornar regras de programa, afetar terceiros, exfiltrar dados ou executar ações destrutivas.
- Submeter relatórios, criar contas, enviar documentos, publicar, pagar ou executar ações remotas em nome do usuário sem aprovação específica.
- Alterar controles de sandbox, habilitar todos os clientes detectados ou instalar ferramentas nativas de análise de forma silenciosa.

## Fluxo proposto
1. `product-lead` recebe o pedido e gerencia o `hacking` após autorização explícita do plano.
2. O usuário fornece o programa, ativos em escopo, regras, métodos proibidos e dados/contas de teste que está autorizado a usar. O agente confere as fontes oficiais e resolve ambiguidades antes de testar.
3. O agente prepara uma matriz priorizada de hipóteses e caminhos positivos/negativos. Classifica cada ação como passiva, ativa não destrutiva ou potencialmente impactante e explica objetivo, risco e alternativa.
4. REA é usado como apoio de reverse engineering, observação e evidência local. A instalação/configuração fica restrita ao cliente Codex e inicia com uma prévia oficial revisável.
5. O agente executa testes permitidos e proporcionais ao plano. Qualquer mudança de escopo, método proibido/ambíguo, dados sensíveis, impacto material ou ação externa pausa até decisão humana. Autorização do usuário não sobrepõe as regras do programa.
6. O agente apresenta achados verificáveis separados de hipóteses; o `product-lead` gerencia handoff e o `product-qa` mantém revisão independente quando houver alterações de código/configuração.
7. O agente prepara o relatório e explica como o usuário pode submetê-lo e acompanhar a triagem; não declara bounty nem pagamento sem confirmação da plataforma.

## Limites de segurança e operação
- Cada avaliação requer URL/fonte oficial do programa, escopo explícito e política vigente. Não realizar varredura ampla de ativos descobertos por associação.
- Não executar DoS, spam, brute force/credential stuffing, phishing/engenharia social, persistência, evasão, alteração destrutiva, acesso a dados de terceiros ou exfiltração. Usar contas/dados próprios ou de teste e interromper ao confirmar o impacto mínimo necessário.
- Manter limites de taxa e janelas do programa. Sem limite informado, escolher o método menos intrusivo e perguntar antes de aumentar intensidade.
- Não guardar nem repetir segredos, tokens, dados pessoais ou dados de outros clientes nos relatórios. Redigir/mascarar evidências.
- A integração MCP do REA é configurada no cliente Codex e não cria sandbox individual por agente. As instruções do perfil não substituem permissões do runtime nem as regras aplicadas pela ferramenta/servidor. Não usar o perfil como isolamento de segurança.
- A instalação deve usar apenas o cliente Codex, executar `--dry-run` primeiro, inspecionar as mudanças propostas e preservar configurações preexistentes. Não instalar Hopper/Ghidra ou outros provedores nativos sem uma necessidade aprovada.

## Critérios de aceite
- **AC-1:** `agents/hacking.toml` define o agente como pesquisador bug bounty autorizado, subordinado ao `product-lead`, sem se apresentar como scanner/garantia de recompensa.
- **AC-2:** O perfil exige fonte oficial de autorização e escopo explícito antes de avaliar um alvo; ausência/ambiguidade bloqueia o teste desse alvo.
- **AC-3:** O perfil inclui cobertura de caminhos negativos e casos-limite com prioridade, risco, evidência e limites de impacto.
- **AC-4:** O perfil limita ação ao escopo e veta atividades proibidas/destrutivas listadas, com pausa para aprovações em decisões ou efeitos materiais.
- **AC-5:** O `product-lead` documenta quando e como gerencia/encaminha trabalho ao agente; README e exemplo apresentam o agente e seus limites.
- **AC-6:** REA é configurado somente para Codex após prévia revisada; não há `--all-detected` nem instalação de engines nativos sem autorização específica.
- **AC-7:** A saída do agente separa fatos, inferências, impacto/confiança e evidências e prepara relatório de bounty sem submeter automaticamente.
- **AC-8:** Os perfis TOML passam análise sintática; diffs/configuração são revisados; nenhum teste é executado contra alvo real nesta entrega.

## Riscos e limitações
- REA pode ser útil para entender o comportamento e produzir evidência, mas sua cobertura não equivale a detecção automática de vulnerabilidades.
- Um servidor MCP configurado para Codex pode ficar disponível a outros agentes/sessões desse cliente; o perfil não fornece isolamento determinístico.
- Regras de programas podem mudar e divergir por ativo; cada execução deve consultar a fonte oficial vigente.
- Resultado de bounty depende de validade, duplicidade, severidade, elegibilidade e decisão do programa; recompensa não é garantida.

## Decisões registradas
- Nome solicitado: `hacking`.
- Especialidade: bug bounty autorizado.
- Gestor: `product-lead`.
- REA: ferramenta de apoio, configurada para Codex com prévia revisável.
- Branching: `develop` local foi criado a partir de `main`; implementação em `feature/hacking-bugbounty-rea`.
- Push remoto não faz parte deste escopo sem pedido explícito separado.
