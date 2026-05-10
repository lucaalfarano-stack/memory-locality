# Local-First Long-Term Memory for LLMs

A local-first long-term memory system for LLMs.

This project extracts conversational memories from ChatGPT exports, indexes them into Redis Stack using vector embeddings, retrieves semantically relevant episodic context, and builds compact memory packages for downstream LLMs.

The goal is not to replace LLM reasoning, but to improve contextual continuity across fragmented conversations while keeping the retrieval layer simple, deterministic, and inspectable.

The system is designed around a simple principle:

> embeddings perform recall,
> retrieval preserves locality,
> the final LLM performs reasoning.

---

# Philosophy

This project intentionally avoids:

- heavy knowledge graph engineering
- manually curated ontologies
- complex agent systems
- symbolic reasoning pipelines

Instead, it focuses on:

- semantic recall
- lightweight locality filtering
- compact episodic memory packaging
- local-first architecture
- simple inspectable code
- leveraging modern LLM reasoning directly

The memory system retrieves.
The downstream LLM reasons.

---

# Features

- Export ChatGPT conversations into text files
- Extract structured events using Ollama
- Index chunks and events into Redis Stack
- Semantic vector retrieval using sentence-transformers (all-MiniLM-L6-v2)
- Mixed retrieval:
  - conversational chunks
  - structured event memories
- Lightweight lexical anchoring to reduce topic drift
- Memory grouping for stronger semantic locality
- Prompt generation for downstream LLMs
- Optional local answering through Ollama

---

# Current Architecture

Pipeline:

```text
ChatGPT exports
    ↓
Conversation chunks (.txt)
    ↓
Structured event extraction (Ollama)
    ↓
Chunk + event embeddings
    ↓
Redis Stack vector indexing
    ↓
Semantic retrieval
+ lightweight lexical anchoring
+ memory grouping
    ↓
Compact episodic context packaging
    ↓
Final LLM reasoning
```

The retrieval layer intentionally remains conservative.

Rather than aggressively rewriting queries or performing intermediate reasoning, the system focuses on preserving semantic locality and reducing cross-domain contamination between memories.

---

# Future Directions

Current experimentation areas:

- retrieval precision tuning
- memory deduplication
- adaptive locality windows
- better episodic grouping
- lightweight hybrid lexical/vector scoring
- memory aging and pruning
- improved event extraction quality

---

# What This Project Is NOT

This is not:

- an autonomous AI agent
- a replacement for LLM reasoning
- a handcrafted knowledge graph system
- a symbolic expert system
- a manually curated ontology

The objective is intentionally narrower and more practical:

> retrieve the right memories at the right time and let the LLM reason over them.

---

# Lessons Learned So Far

A few important findings emerged during development:

## 1. Semantic recall alone is not enough

Pure embedding similarity gives strong recall, but retrieval precision degrades as memory volume grows.

Semantically adjacent but unrelated memories easily leak into prompts, especially across nearby conversational domains.

Example:

Query:

```text
acqua abitacolo auto tappetini
```

Naive semantic retrieval produced unrelated memories involving:
- house condensation
- mortgages
- hospitalization related discussions
- automation systems

because embeddings alone collapsed semantically adjacent conversational contexts.

After lightweight locality filtering:
- flooded driver-side floor
- cabin moisture
- evaporator drainage
- wet floor mats
- water infiltration

Retrieval quality improved significantly without introducing additional reasoning layers.

---

## 2. Overengineering memory structure is risky

Early experiments around:
- entity normalization
- fact classification
- relationship extraction
- graph modeling
- domain taxonomies

quickly increased complexity without proportionally improving answer quality.

Modern LLMs already perform much of this reasoning internally.

---

## 3. Memory packaging matters more than symbolic modeling

The biggest gains came from:
- cleaner memory snippets
- reducing retrieval noise
- better context assembly
- concise prompt construction

rather than deeper symbolic structure.

---

## 4. Overly interpretative retrieval is fragile

Experiments with:
- query rewriting
- aggressive reranking
- semantic expansion
- intermediate reasoning layers

often degraded retrieval stability instead of improving it.

The best results so far come from conservative retrieval:
- semantic recall
- lightweight locality filtering
- compact memory packaging
- reasoning delegated entirely to the final LLM

---

## 5. Episodic locality matters

One of the hardest problems is not memory recall itself, but preventing semantically nearby memories from contaminating each other.

Long conversations naturally drift across domains:
health, finance, cars, software, personal logistics, etc.

Memory grouping and lightweight lexical anchoring currently provide a simpler and more stable solution than deeper symbolic structures.

---

# Project Status

Current maturity level:

## Working well
- local indexing
- semantic retrieval
- memory resurfacing
- prompt augmentation
- local inference via Ollama

## Still experimental
- reranking
- retrieval precision tuning
- query expansion
- memory deduplication
- relevance scoring

The project is currently best viewed as:

> a practical local-first episodic memory layer for LLMs.

The project should currently be considered an experimental systems prototype rather than a production-ready framework.

---

# Observed Failure Modes

- semantic topic contamination
- conversational drift across domains
- reranking instability
- query over-interpretation
- memory flooding from long chats

---

# Repository Structure

The implementation intentionally lives mostly in a single file:

```text
main.py
```

The single-file structure is currently intentional.

The project is still evolving quickly, and keeping retrieval, indexing and prompt construction visible in one place makes experimentation substantially easier.

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

Desired retrieval behavior:

- recover relevant memories from past chats
- avoid unrelated domains
- preserve useful context
- let the downstream LLM combine:
  - retrieved memories
  - general automotive knowledge

into a grounded answer.

The system should avoid premature reasoning.
Its role is memory retrieval and contextual packaging.

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
    → chunk extraction
    → event extraction
    → embedding generation
    → Redis indexing
    → semantic retrieval
    → memory packaging
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

This repository is intentionally open and local-first.