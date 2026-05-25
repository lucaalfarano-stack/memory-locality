# Ordered Memory Observations

## Context

This project started as a local-first long-term memory system for LLMs based on:

- conversational chunking
- embeddings
- semantic retrieval
- lightweight locality filtering
- episodic grouping

The original assumption was relatively standard:

> embeddings perform retrieval  
> locality reconstruction improves context  
> the final LLM performs reasoning

Over time, several retrieval pathologies started appearing consistently:

- semantic topic drift
- contamination between nearby conversational domains
- unstable reranking
- semantic over-expansion
- fragmentation of conversational continuity

This led to experimentation around ordered conversational memory and lexical positional retrieval.

---

# Architectural Shift

## Initial architecture (v0.1)

```text
conversation chunks
→ embeddings
→ vector retrieval
→ locality grouping
→ prompt packaging
→ LLM reasoning
```

Main characteristics:

- chunk-centric
- semantic-first
- retrieval after fragmentation
- locality reconstructed after retrieval

---

## Current experimental architecture

```text
ordered conversations
→ lexical anchor acquisition
→ positional retrieval
→ local conversational expansion
→ LLM reasoning
```

Main characteristics:

- conversation-centric
- locality-first
- retrieval over ordered memory
- minimal semantic interpretation
- sparse anchor layer

---

# Main Observations

## 1. Ordered locality matters more than expected

One of the strongest observations so far is that preserving conversational adjacency directly at retrieval time significantly improves contextual reconstruction.

The system behaves more coherently when retrieval lands inside the correct conversational neighborhood, even if retrieval itself is relatively simple.

This differs from classic RAG systems where retrieval units are typically independent semantic chunks.

Conversation histories appear strongly:

- temporal
- adjacency-sensitive
- episodic
- continuity-dependent

---

## 2. Semantic retrieval alone degrades over time

Pure embedding similarity often retrieves semantically adjacent but contextually unrelated memories.

Examples observed during experiments:

### Query

```text
acqua abitacolo auto tappetini
```

### Incorrect retrieval contamination

- house condensation
- humidity problems
- mortgage discussions
- unrelated logistics
- automation systems

The issue becomes more severe as conversational history grows.

---

## 3. Aggressive semantic reconstruction often makes retrieval worse

Several experiments around:

- query rewriting
- semantic expansion
- reranking
- intermediate reasoning
- graph enrichment

often reduced retrieval precision instead of improving it.

The system frequently became over-interpretative.

This produced:

- topic blending
- narrative averaging
- memory contamination
- unstable prompts

---

## 4. Lexical landing + locality behaves surprisingly well

Experiments using lexical anchor acquisition followed by local conversational expansion produced retrieval behavior that often felt more stable and "human".

Observed retrieval flow:

```text
lexical hit
→ positional landing
→ neighboring conversational turns
→ LLM reconstruction
```

This often outperformed more elaborate semantic pipelines.

---

## 5. Events as semantic summaries did not work well

Early event extraction produced highly specific semantic abstractions.

Example failure mode:

```text
one extracted event
↔ one conversation
```

This created almost no useful recurrence across memory.

The topology became sparse and disconnected.

---

## 6. Lightweight recurring anchors work better

The current direction replaces semantic "events" with lightweight recurring anchors.

Examples:

```text
globuli
ricovero
docker
redis
leucemia
peugeot
```

instead of highly specific semantic descriptions.

The role of anchors becomes:

- navigational
- positional
- retrieval-oriented

rather than semantic summarization.

---

## 7. The retrieval problem changed over time

Early failures were mostly:

- retrieval failure
- semantic contamination
- incorrect conversational landing

Current failures are increasingly:

- anchor saliency
- answer prioritization
- numeric fidelity
- identity reconstruction

This is an important shift.

It suggests that retrieval topology improved significantly.

---

# Redis Arrays and ARGREP

A major influence on the current direction came from experiments around Redis Arrays and ARGREP proposed by Salvatore Sanfilippo.

The key idea is that conversational memory may behave more like:

- ordered files
- sparse indexed logs
- append-only conversational streams

than traditional semantic document collections.

Relevant properties:

- positional retrieval
- locality preservation
- lexical grep-oriented access
- sparse indexing
- ordered memory substrate

The current implementation still emulates this behavior using Redis Lists.

Future versions may experiment directly with:

- `ARSET`
- `ARGREP`
- `ARSCAN`
- ordered sparse arrays

from the Redis unstable branch.

---

# Current Experimental Retrieval Model

Current retrieval direction:

```text
ordered conversational memory
→ sparse lexical anchors
→ positional retrieval
→ local conversational expansion
→ LLM reasoning
```

Semantic retrieval may still remain useful, but increasingly as:

```text
anchor acquisition
```

rather than full memory reconstruction.

---

# Observed Failure Modes

## Semantic contamination

Semantically adjacent memories contaminate each other.

---

## Identity ambiguity

Queries like:

```text
chi è Enrico?
```

are difficult because lexical recurrence alone is insufficient.

Entity mentions become overspread across conversations.

---

## Numeric corruption

LLMs sometimes normalize retrieved numbers incorrectly:

```text
410.000
→ 41000
```

even when retrieval itself is correct.

---

## Anchor overspread

Very common entities produce weak positional specificity.

Example:

```text
Enrico
```

appears in many unrelated conversational moments.

---

# Emerging Hypotheses

## 1. Conversation itself may be the memory substrate

Not:
- semantic summaries
- extracted facts
- symbolic structures

but ordered conversational continuity itself.

---

## 2. Semantic retrieval may be most useful only for anchor acquisition

Instead of reconstructing memory semantically, semantic retrieval may simply help identify:

- where to land
- which conversational region to expand

---

## 3. Positional retrieval appears more stable than semantic reranking

Ordered locality reconstruction currently appears more robust than aggressive semantic processing.

---

## 4. Different query types may require different anchor strategies

Examples:

### factual recall

```text
quanti globuli bianchi aveva Enrico al ricovero?
```

### episodic reconstruction

```text
cosa successe durante il primo ricovero?
```

### identity reconstruction

```text
chi è Enrico?
```

These likely require different anchor acquisition strategies.

---

# Suggested Future Experiments

## Compare retrieval architectures

- vector retrieval
- ordered retrieval
- argrep-style retrieval
- hybrid anchor acquisition

---

## Compare against ChatGPT memory behavior

- ChatGPT with memory
- ChatGPT temporary chat
- local ordered memory retrieval

---

## Measure retrieval drift over longer histories

Especially:

- healthcare
- finance
- software
- vehicles
- personal logistics

inside the same conversation timelines.

---

# Current Conclusion

The experiments increasingly suggest that conversational memory retrieval behaves differently from traditional document RAG systems.

The strongest current signal is:

```text
lexical landing
+ ordered locality
+ minimal interpretation
```

may produce more stable conversational memory reconstruction than heavily semantic retrieval pipelines.
