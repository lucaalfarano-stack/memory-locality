# memory-locality — Project Overview

## What memory-locality is

memory-locality is a local-first conversational-memory system. It reconstructs useful conversational context from chronological order, positional locality, and lexical/event anchors, without relying on a persistent database or a heavyweight knowledge graph.

Its core job is not to make retrieval perfectly understand a conversation. It is to land retrieval in the right **temporal neighbourhood**, then give a downstream language model enough nearby context to reason accurately.

## Problem it solves

Long conversations accumulate facts, symptoms, decisions, and evolving topics. Standard keyword search loses context; broad semantic retrieval can return relevant but temporally wrong fragments; complex memory graphs add operational cost and brittle assumptions.

memory-locality targets questions whose answer depends on where an idea appears in the conversation, such as:

- “When did I first start talking about this symptom?”
- “What was decided after that event?”
- “How did this topic develop over time?”

## Non-goals

- Building a general-purpose persistent knowledge base.
- Maintaining a heavyweight entity or relationship graph.
- Replacing downstream LLM reasoning with increasingly complex retrieval heuristics.
- Guaranteeing a complete semantic interpretation from isolated chunks alone.
- Optimizing for maximum feature surface before the basic locality model is validated.

## Architectural principles

1. **Chronology is data.** Message/event order is a primary retrieval signal, not incidental metadata.
2. **Landing before reasoning.** Retrieval identifies a promising local area; the LLM interprets the evidence.
3. **Local expansion preserves meaning.** Once a landing point is found, adjacent messages often contain the introduction, qualification, and resolution that a single chunk misses.
4. **Events beat raw words.** Prefer salient anchors extracted during event processing over simple single-word matching when available.
5. **Keep the system local-first and light.** Avoid persistent stores and elaborate graph machinery unless evidence proves they are necessary.

## Current architecture

```text
conversation/messages
        ↓
event extraction and salient anchors
        ↓
lexical or lightweight semantic landing
        ↓
chronological ordering and positional selection
        ↓
asymmetric local-context expansion
        ↓
LLM verification and answer
```

The retriever may produce several candidates. It should preserve their chronological positions and return enough surrounding evidence for verification, rather than treating a single retrieval score as the final answer.

## Design philosophy

The project favors a small, inspectable pipeline over an elaborate memory stack. Retrieval only has to locate the right neighbourhood; the language model can then apply temporal and semantic reasoning to the local evidence. Architectural decisions are treated as hypotheses until they are tested against real conversation cases.

## Current status — Phase 1: Earliest Mention

The active milestone is **Earliest Mention**, for questions like “When did I start talking about [topic]?”

The intended flow is:

1. Find chunks/events containing relevant lexical or event anchors.
2. Order candidate occurrences chronologically and treat the minimum index/timestamp as the **earliest candidate**, not an unquestionable result.
3. Expand primarily forward from that candidate (roughly 1–2 messages before and 4–5 after) because a topic often develops immediately after its first introduction.
4. Ask the LLM to verify the date and distinguish a genuine first introduction from an earlier marginal reference.

## Roadmap — five retrieval strategies

The roadmap is organized as five query-oriented retrieval strategies. Only the first is the current validated implementation target; the others remain product hypotheses to define and test against real data.

1. **Earliest Mention** — locate and verify the first meaningful introduction of a topic.
2. **Latest Mention** — locate the most recent meaningful update or state of a topic.
3. **Topic Evolution** — retrieve chronological local windows that show how a topic changed.
4. **Event/Decision Context** — retrieve the local context around a named event, decision, or commitment.
5. **Recurring Topic Synthesis** — identify separated local neighbourhoods for a recurring theme, leaving synthesis to the LLM.

Each strategy should reuse the same core pattern: anchor-led landing, position-aware selection, local expansion, and final LLM verification.
