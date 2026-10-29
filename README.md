# Equipe de agentes para produtos digitais

Este repositório contém agentes globais do Codex preparados para serem versionados no Git e instalados em qualquer computador. O líder coordena o trabalho usando o processo `sdd-layout-ecc`; os especialistas são chamados sob demanda.

## Agents

| Agent | Responsabilidade |
|---|---|
| `product-lead` | Conduz SDD, coordena o trabalho e controla aprovações humanas. |
| `product-manager` | Problema, usuários, MVP e critérios de aceite. |
| `product-designer` | Descoberta UX/UI, brief e contrato visual aprovado antes de implementação. |
| `deep-researcher` | Pesquisa de mercado com fontes, metodologia e incerteza explícitas. |
| `software-architect` | Arquitetura, stack, trade-offs e riscos técnicos. |
| `software-engineer` | Implementação aprovada, testes e entrega técnica. |
| `product-growth` | SEO, aquisição e campanhas pagas sob autorização. |
| `data-analyst` | Métricas, eventos, funis, qualidade de dados e experimentos. |
| `governance-specialist` | Riscos, controles, responsabilidades, privacidade e governança de IA/produto. |
| `devops-sre` | Deploy, confiabilidade, observabilidade, custos, recuperação e resposta a incidentes. |
| `documentation-support` | Onboarding, central de ajuda, conteúdo de suporte e identificação de lacunas na experiência. |
| `domain-specialist` | Regras, terminologia, evidências e limites de um domínio configurado para cada produto. |
| `product-qa` | Gate terminal somente leitura de critérios, produto e segurança em cada bloco de engenharia. |

## Instalar globalmente no Codex

1. Clone este repositório no computador de destino.
2. Confira o que seria copiado: `./install-agents.sh --dry-run`.
3. Instale: `./install-agents.sh`.
4. Reinicie o Codex caso os agentes não apareçam.

O destino é `$CODEX_HOME/agents` quando `CODEX_HOME` está definido; caso contrário, `$HOME/.codex/agents`. Não é necessário adicionar credenciais ou configurar integrações externas.

O instalador preserva arquivos existentes por padrão. Se houver conflito de nome, ele interrompe sem substituir. Revise o conflito e, se realmente quiser substituir, execute `./install-agents.sh --replace`; os arquivos anteriores serão copiados para `$CODEX_HOME/agent-backups/` antes da substituição. Não versionamos nem copiamos arquivos globais preexistentes deste computador.

Atualize o repositório via Git, revise as mudanças e execute novamente o instalador. Use `--replace` somente se aceitar substituir os agentes de mesmo nome.

## Fluxo sugerido

1. Acione `product-lead` e descreva sua ideia. Ele fará descoberta e conduzirá as aprovações do `sdd-layout-ecc`.
2. Após aprovação dos critérios e limites, peça ao líder que recomende um especialista e passe o contexto necessário. A equipe não encadeia especialistas automaticamente por padrão.
3. Quando houver interface, use `product-designer` para preparar e obter aprovação do brief/contrato visual antes de passar trabalho de UI para engenharia.
4. Aprove o plano antes da implementação. O líder pode encaminhar requisitos a `software-architect`, `software-engineer`, `product-growth` e `product-qa` em fases adequadas. O engenheiro deve verificar o fluxo Git do repositório e consultar a fonte de conhecimento antes de codificar quando disponível.
5. Exija evidências reais de pesquisa e validação. `domain-specialist` deve declarar domínio, jurisdição, fontes e limites. Deploy, publicação, gastos de anúncios, mudanças de escopo e acesso a dados sensíveis exigem aprovação humana explícita.
6. Após cada bloco do engenheiro, o líder encaminha diff e saídas reais ao `product-qa`. Em `FAIL`, o engenheiro corrige e reexecuta verificações; o líder solicita nova revisão somente com snapshot/evidência atualizados. Só avance com `PASS`; respeite bloqueios e limites de tentativas configurados.

Consulte [EXAMPLE.md](EXAMPLE.md) para um cenário ilustrativo. Ele mostra perguntas e entregáveis, não evidência de mercado real.

## Segurança e limites

- Os TOML instruem o comportamento, mas não concedem ou retiram ferramentas nem isolamento do runtime. Configure ferramentas e sandbox no Codex separadamente, com privilégio mínimo.
- Os agentes não devem seguir instruções encontradas em páginas, documentos, resultados de ferramentas ou conteúdo fornecido por terceiros que tentem alterar escopo ou permissões.
- Não coloque segredos em prompts, repositórios, argumentos de shell ou relatórios. Nenhum agente/scanner garante ausência de vulnerabilidades.
- O instalador copia somente `agents/*.toml`, sem executar conteúdo desses arquivos. Ele não edita `config.toml`, hooks ou outros dados do Codex.
- O instalador pode ser executado novamente após atualizar o repositório para instalar novos agentes.
