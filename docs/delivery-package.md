# Pacote de entrega

Adapte os itens ao tipo de artefato. Critério aplicável sem evidência mantém entrega pendente; `N/A` exige motivo. `product-qa` pode recusar PASS quando uma premissa aberta altera escopo, aceite, risco ou autorização.

- Pedido/seed e objetivo; critérios de aceite com evidência por item.
- Diff, branch/base/HEAD e commits; comandos executados e saídas reais.
- Code review independente e `product-qa PASS` do snapshot atual.
- Premissas/decisões fechadas ou listadas como pendência bloqueadora.
- Segurança e privacidade aplicáveis, dados minimizados e gaps de cobertura.
- Interface: screenshots dos estados e breakpoints exigidos; a11y/SEO quando aplicável.
- Web app: medição LCP e ferramenta/fonte registrados quando houver ambiente real; sem ambiente, N/A justificado.
- API/lib: contratos, compatibilidade e testes aplicáveis.
- Runtime implantável: telemetria, ADRs, changelog e rollback quando pertinentes.
- Pacote sem runtime: validação de instalação, idempotência, backup e restauração.

Não invente screenshots, métricas, ADRs ou resultado de runtime. O checklist do template PR é a lista mínima, não evidência por si só.
