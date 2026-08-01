# memory-locality — Project State

## Purpose

This is the bootstrap document for coding assistants and new contributors. Read it before proposing architecture or changing retrieval behaviour. It records the current intended state; when it conflicts with executable code or tests, inspect the discrepancy and raise it rather than silently replacing a decision.

## Repository structure

At the time this document was created, this ChatGPT Project workspace contains no synced application repository or source files. The expected project layout is therefore not yet verifiable here.

- `docs/project-overview.md` — product and architectural overview.
- `docs/project-state.md` — current working context for implementation.
- Application code, tests, README, and experiment notes — to be added or synced with the actual `memory-locality` repository.

When the repository is available, update this section with the actual entry point, test locations, event schema, and retrieval pipeline boundaries.

## Current implementation summary

The intended system is local-first conversational-memory retrieval based on chronological order, positional locality, and lexical/event anchors. The known pipeline is:

1. represent messages or chunks in chronological order;
2. extract events and salient anchors where possible;
3. use lexical or lightweight semantic matching to land on candidate chunks/events;
4. expand a small local context window around a candidate; and
5. use an LLM to verify and formulate the answer.

No source implementation is present in this workspace to validate interfaces, dependencies, or test coverage. Do not assume a database, graph, vector store, or module layout exists until the repository is connected.

## Validated architectural decisions

- Retrieval should find a good temporal neighbourhood, not perform all reasoning itself.
- Use lightweight lexical/semantic landing followed by positional locality expansion.
- Preserve chronological indices/timestamps as first-class signals.
- Prefer salient event anchors over naive single-token matches when event extraction is available.
- Keep the design local-first; avoid persistent databases and heavyweight graphs by default.
- Let the downstream LLM verify candidate evidence, especially when an early hit could be marginal or ambiguous.

## Current branch/release status

Not verifiable in this Project workspace: it is not currently a Git working tree and has no synced repository files. Once the repository is connected, record the active branch, latest release/tag, and any local uncommitted work here.

## Current milestone

**Phase 1 — Earliest Mention.**

Implement support for questions asking when a topic, symptom, or event was first meaningfully discussed. The working retrieval behaviour is:

- land on chunks/events via lexical or event anchors;
- chronologically order candidates and select the minimum position as an earliest *candidate*;
- expand asymmetrically: approximately 1–2 messages backward and 4–5 forward;
- have the LLM confirm the exact date and whether the occurrence is a true introduction rather than a marginal mention.

## Immediate next steps

1. Sync or link the actual `memory-locality` repository and replace the provisional structure/status notes above.
2. Locate the existing event extraction and retrieval entry points.
3. Implement or verify earliest-candidate ordering by `index_0` or `timestamp_min`.
4. Implement the asymmetric forward locality window.
5. Add representative tests: true first introduction, earlier incidental mention, multiple candidate events, and date verification.
6. Record observed retrieval failures before adding new abstractions or storage systems.

## Coding guidelines

- Prefer minimal, inspectable changes that preserve the existing design.
- Keep code in one Python file when practical; split only when a concrete maintenance need appears.
- Avoid overengineering, new persistence layers, heavyweight graphs, and speculative abstractions.
- Preserve chronological positions and return evidence suitable for LLM verification.
- Add or update focused tests when changing retrieval logic.
- Treat previous architectural decisions as intentional unless explicitly challenging them with evidence.

## Important documents to read, in order

1. `README.md` — setup, public API, and project scope (when synced).
2. `docs/project-overview.md` — product goal and architectural principles.
3. `docs/project-state.md` — current milestone and implementation constraints.
4. `docs/experiments.md` — experiment outcomes and measured behaviour (when present).
5. `docs/ordered-memory-observations.md` — observations behind the locality approach (when present).
6. Relevant source code and tests — the executable source of truth.
