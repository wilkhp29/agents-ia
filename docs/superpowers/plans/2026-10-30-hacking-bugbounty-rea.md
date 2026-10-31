# Agente Hacking Bug Bounty com REA — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar o agente `hacking` à equipe, integrá-lo ao fluxo do `product-lead` e habilitar REA no cliente Codex para análises de bug bounty autorizadas.

**Architecture:** `product-lead` mantém ownership, gates e comunicação com o usuário. `hacking` conduz a investigação autorizada e usa REA como apoio; `software-engineer` continua responsável por código e `product-qa` pela revisão independente. O servidor MCP REA é configurado no cliente Codex, sem alegar isolamento exclusivo por perfil.

**Tech Stack:** Codex agent TOML, Markdown, REA MCP via `rea-agents`, Git.

---

### Task 1: Criar o perfil do agente

**Files:**
- Create: `agents/hacking.toml`

- [x] Definir especialidade bug bounty e subordinação ao `product-lead`.
- [x] Exigir fonte oficial do programa, escopo por ativo, métodos permitidos/proibidos, limites de taxa e janela antes de testar; sem limite de taxa oficial claro, não permitir testes ativos até esclarecer a regra, admitindo apenas observação passiva se permitida pela política.
- [x] Incluir plano de testes positivos/negativos, limites, estados de erro, autorização, falhas e sequências incomuns dentro do escopo.
- [x] Proibir DoS, brute force, phishing/engenharia social, persistência, evasão, exfiltração, acesso a dados de terceiros, alteração destrutiva e teste fora do programa.
- [x] Definir o uso do REA para reverse engineering/evidências, sem tratá-lo como scanner ou garantia de detecção.
- [x] Exigir explicação e aprovação antes de ação fora do plano ou de impacto material; preparar relatório sem submissão automática nem promessa de recompensa.

### Task 2: Integrar agente à equipe

**Files:**
- Modify: `agents/product-lead.toml`
- Modify: `README.md`
- Modify: `EXAMPLE.md`
- Modify: `docs/superpowers/specs/2026-10-30-hacking-bugbounty-rea-design.md`

- [x] Registrar o agente como especialista de bug bounty que o líder gerencia após o gate explícito de plano.
- [x] Documentar handoff de programa/escopo/regras, evidências e aprovação ao agente.
- [x] Documentar que o REA MCP do Codex pode ser herdado por outras sessões e não dá isolamento por TOML.
- [x] Marcar a especificação como aprovada e manter requisitos/limites alinhados ao perfil.

### Task 3: Configurar REA para Codex

**Files:**
- Codex user configuration (managed by official REA setup; preserve unrelated settings).

- [x] Confirmar versão Node compatível com REA.
- [x] Executar `rea-agents@6.8.0 setup --client codex --dry-run` com Node 24.22.1 e inspecionar a proposta completa.
- [x] Aplicar somente a configuração para Codex depois de conferir que não inclui outros clients, instalação de Hopper/Ghidra ou mudanças fora do plano.
- [x] Confirmar registro `mcp_servers.rea` e skill global no disco. Reiniciar o Codex para carregar o servidor MCP; handshake ainda não verificado nesta sessão.

### Task 4: Revisar, validar, instalar e entregar

**Files:**
- Install `agents/*.toml` into `$CODEX_HOME/agents` through `install-agents.sh`.

- [x] Analisar sintaxe de todos os perfis TOML e executar `git diff --check`.
- [x] Conferir o dry-run do instalador global, substituir conflitos com backup e conferir hashes dos perfis alterados.
- [x] Revisar o diff contra os critérios de aceite; nenhum alvo de bounty será acessado nesta entrega.
- [x] O líder cria commit(s) locais na feature branch antes do handoff ao `product-qa`; QA revisa o snapshot exato em somente leitura.
- [ ] Após `PASS`, integrar na `main` e enviar o push autorizado pelo usuário; confirmar `origin/main` no SHA final.
