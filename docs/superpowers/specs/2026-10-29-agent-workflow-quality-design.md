# Melhoria do fluxo e da qualidade das entregas

## Objetivo
Tornar o fluxo multiagente consistente, reduzir retrabalho e fazer cada aprovação e resultado de QA rastreáveis à evidência revisada.

## Decisões aprovadas
- Git Flow permanece a regra global: README e exemplo devem corresponder ao perfil de engenharia.
- Todo handoff deve carregar objetivo, critérios, decisões, fora de escopo, riscos, áreas afetadas e evidências.
- Uma aprovação explícita cobre o escopo e o plano identificados; não se pede novamente para passos reversíveis que já estão dentro desse limite. Mudanças de escopo, custo, risco, dados sensíveis, interface sem contrato aprovado ou operações de produção mantêm gates humanos.
- QA mapeia cada critério a evidências, comandos e resultado, e registra o snapshot (HEAD/base/diff) revisado.
- Skills e ferramentas de QA são usadas quando disponíveis. Caminhos de outra máquina são removidos; alternativas manuais registram cobertura e lacunas sem mascarar verificações essenciais indisponíveis.
- O README define métricas operacionais simples e uma revisão periódica, sem inventar metas antes de haver baseline.

## Arquivos e responsabilidades
- `README.md`: fluxo normativo, handoff comum, gates, métricas e cadência de revisão.
- `EXAMPLE.md`: cenário prático alinhado ao fluxo normativo.
- `agents/product-lead.toml`: aprovação vinculada ao escopo e handoff padronizado.
- `agents/software-engineer.toml`: entrega com critérios, snapshot Git e evidências atuais.
- `agents/product-qa.toml`: revisão rastreável e fallback de ferramentas/skills.

## Fora de escopo
Mudar a política de Git Flow, automatizar aprovações, criar integrações ou testes, adicionar metas de KPI sem baseline, alterar o instalador, ou mudar gates para deploy, publicação e acesso a dados sensíveis.
