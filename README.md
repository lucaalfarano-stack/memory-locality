# memory-locality

Local-first conversational memory retrieval for LLMs.

This project explores an alternative approach to long-term conversational memory based on:

- ordered conversational locality
- lightweight lexical anchoring
- conservative retrieval
- inspectable memory reconstruction

instead of aggressive semantic reranking or heavily abstracted memory graphs.

The system extracts conversational histories, indexes them into Redis, retrieves relevant conversational regions, reconstructs local continuity, and provides contextual memory packages for downstream LLMs.

The core idea is simple:

> retrieve the right conversational neighborhood and let the LLM reason over it.

---

# Current Direction

The project originally started as a semantic vector-retrieval system.

Over time, experiments showed that conversational memory behaves differently from traditional document retrieval:

- semantic similarity alone often causes topic contamination
- aggressive reranking easily over-interprets memory
- conversational continuity matters more than expected
- locality reconstruction is often more important than semantic expansion

The current architecture increasingly focuses on:

- ordered conversational memory
- locality-preserving retrieval
- lightweight anchor acquisition
- minimal intermediate reasoning
- explicit retrieval inspectability

The retrieval layer retrieves.
The downstream LLM reasons.

---

# Features

- Export ChatGPT conversations into text files
- Ordered conversational memory indexing
- Lightweight lexical anchor extraction
- Semantic vector recall
- Locality-preserving retrieval
- Episodic conversational expansion
- Prompt/context packaging for downstream LLMs
- Optional local answering through Ollama
- Inspectable retrieval traces

---

# Current Architecture

Current retrieval flow:

```text
ChatGPT exports
    ↓
conversation extraction
    ↓
ordered conversational indexing
    ↓
lightweight anchor extraction
    ↓
semantic + lexical landing
    ↓
local conversational expansion
    ↓
context packaging
    ↓
downstream LLM reasoning
```

The system intentionally keeps retrieval conservative.

Rather than aggressively rewriting queries or constructing symbolic memory graphs, the project focuses on:

- conversational landing precision
- locality preservation
- retrieval inspectability
- minimizing semantic contamination

---

# Current Research Areas

Current exploration areas include:

- anchor saliency ranking
- ordered conversational retrieval
- hybrid lexical/semantic landing
- retrieval trace visualization
- lightweight semantic disambiguation
- conversational continuity reconstruction
- memory aging and pruning
- deterministic retrieval evaluation

---

# Key Observations

Several consistent patterns emerged during experimentation.

## Semantic retrieval alone is unstable

Pure embedding similarity retrieves semantically adjacent but contextually unrelated memories surprisingly often.

As conversational histories grow, nearby domains begin contaminating each other:

- health
- finance
- software
- vehicles
- personal logistics

This creates semantic drift and unstable retrieval.

---

## Ordered conversational locality matters

Retrieval quality improved significantly when the system landed inside the correct conversational neighborhood before expanding context.

The strongest improvements came from:

- locality preservation
- positional continuity
- episodic adjacency
- lightweight lexical landing

rather than aggressive semantic reranking.

---

## Over-interpretative retrieval is fragile

Experiments with:

- query rewriting
- aggressive reranking
- semantic expansion
- graph enrichment

often degraded retrieval quality instead of improving it.

The best results currently come from:

```text
lightweight retrieval
+ locality reconstruction
+ minimal interpretation
```

---

## Retrieval and synthesis are separate problems

As retrieval quality improved, another distinction became clear:

- retrieving the correct conversational region
- generating the correct final answer

are different problems.

Current failures increasingly involve:

- saliency ranking
- synthesis drift
- weak identity reconstruction
- answer prioritization

rather than retrieval collapse itself.

---

# Project Status

Current status:

## Stable

- local indexing
- ordered conversational retrieval
- locality expansion
- prompt augmentation
- Ollama integration
- inspectable retrieval traces

## Experimental

- anchor saliency ranking
- hybrid lexical/semantic retrieval
- identity reconstruction
- synthesis grounding
- retrieval evaluation
- benchmark automation

The project should currently be viewed as:

> an experimental conversational memory architecture for LLM systems.

---

# Repository Structure

The current implementation intentionally lives mostly in a single file:

```text
main.py
```

The single-file structure is currently intentional.

The project is still evolving quickly, and keeping retrieval, indexing and prompt construction visible in one place makes experimentation easier.

This keeps:
- refactoring simple
- global rewrites easy
- debugging transparent
- AI-assisted editing manageable

Future modularization may separate:
- indexing
- retrieval
- prompt building
- reranking
- event extraction

only if complexity genuinely requires it.

---

# Example Goal

User query:

```text
"che problemi ha la mia Peugeot 307?"
```

Desired behavior:

- retrieve conversational regions related to the same vehicle
- preserve temporal and conversational continuity
- avoid contamination from unrelated domains
- reconstruct useful troubleshooting context
- allow the downstream LLM to reason over grounded memory

The retrieval layer should remain simple, inspectable and locality-aware.

---

# Installation

## Requirements

- Python 3.11+
- Redis Stack
- Ollama

---

## Redis Stack

Example using Docker:

```bash
docker run -d \
  -p 6379:6379 \
  redis/redis-stack:latest
```

---

## Ollama

Install Ollama:

https://ollama.com

Pull the model:

```bash
ollama pull phi3
```

---

## Python dependencies

```bash
pip install -r requirements.txt
```

---

# Usage

Typical workflow:

```text
ChatGPT export
    → conversation extraction
    → ordered memory indexing
    → anchor extraction
    → retrieval landing
    → locality expansion
    → context packaging
    → downstream LLM reasoning
```

## 1. Export conversations

```bash
python main.py export \
  --input ./data/raw/conversations.json \
  --output ./data/chunks
```

---

## 2. Extract events

```bash
python main.py events \
  --input ./data/chunks \
  --output ./data/events
```

---

## 3. Index chunks and events

```bash
python main.py index \
  --chunks ./data/chunks \
  --events ./data/events
```

---

## 4. Search memory

```bash
python main.py search \
  --query "problemi Peugeot 307"
```

---

## 5. Ask Ollama directly

```bash
python main.py search \
  --query "problemi Peugeot 307" \
  --ollama
```

---

## 6. Cleanup index

```bash
python main.py cleanup
```

---

# License

MIT License.

This repository is intentionally open, simple and local-first.