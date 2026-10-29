# Agent Workflow Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Align agent workflow docs and profiles to reduce handoff loss and make approvals, QA, and delivery evidence repeatable.

**Architecture:** Keep the existing TOML profiles and README as the source of workflow rules. Put shared process semantics in README and product-lead; specialize evidence and fallbacks in software-engineer and product-qa; keep the example consistent with the rules.

**Tech Stack:** Markdown, TOML, Git.

---

### Task 1: Align workflow documentation

**Files:**
- Modify: `README.md`
- Modify: `EXAMPLE.md`

- [x] State that Git Flow is the current global requirement and explain branch bootstrap from the appropriate primary line.
- [x] Add a reusable handoff record, scope-based approval semantics, QA evidence record, and quality metrics with definitions.
- [x] Update the example so its steps and approval gates match those rules.

### Task 2: Make agent instructions consistent

**Files:**
- Modify: `agents/product-lead.toml`
- Modify: `agents/software-engineer.toml`
- Modify: `agents/product-qa.toml`

- [x] Bind approvals to recorded scope and avoid repeated approval for covered, reversible work.
- [x] Require handoffs and engineering delivery to identify criteria, decisions, scope limits, risks, changed areas, Git snapshot, commands, and evidence.
- [x] Make QA tools/skills environment-aware, remove machine-specific paths, and require explicit coverage/gap reporting for fallbacks.

### Task 3: Review and commit on main

**Files:**
- Review all files above and the design/plan documents.

- [x] Inspect the complete diff for contradictions, accidental scope changes, and whitespace errors.
- [x] Confirm the current branch is `main` and commit all improvements together after review.
