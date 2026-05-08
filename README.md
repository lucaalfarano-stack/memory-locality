# Local LLM Memory Retrieval

A local-first long-term memory system for LLMs.

This project extracts memories from ChatGPT conversations, indexes them into a vector database, retrieves relevant context semantically, and builds enhanced prompts for downstream LLMs.

The goal is not to replace the reasoning capabilities of modern LLMs, but to provide them with better contextual continuity across conversations.

---

# Philosophy

This project intentionally avoids:

- heavy knowledge graph engineering
- manually curated ontologies
- complex agent systems
- symbolic reasoning pipelines

Instead, it focuses on:

- semantic memory retrieval
- compact memory packaging
- local-first architecture
- simple inspectable code
- leveraging modern LLM reasoning directly

The LLM should reason.
The memory system should retrieve.

---

# Features

- Export ChatGPT conversations into text files
- Extract structured events using Ollama
- Index chunks and events into Redis Stack
- Semantic vector retrieval using sentence-transformers
- Mixed retrieval:
  - conversational chunks
  - structured event memories
- Prompt generation for downstream LLMs
- Optional local answering through Ollama

---

# Current Architecture

Pipeline:

```text
ChatGPT export
    ↓
Conversation chunks (.txt)
    ↓
Structured events extraction
    ↓
Redis vector indexing
    ↓
Semantic retrieval
    ↓
Context packaging
    ↓
Enhanced prompt for LLM
```

---

# Future Directions

Potential future improvements:

- lightweight lexical filtering
- better event compression
- temporal memory grouping
- conversation-level summarization
- hybrid lexical + vector retrieval
- graph visualization of memories/events
- memory aging/pruning

---

# What This Project Is NOT

This is not:

- an autonomous AI agent
- a replacement for LLM reasoning
- a handcrafted knowledge graph system
- a symbolic expert system
- a manually curated ontology

The objective is narrower and more practical:

> retrieve the right memories at the right time and let the LLM reason over them.

---

# Lessons Learned So Far

A few important findings emerged during development:

## 1. Vector search alone is not enough

Pure embedding similarity gives decent recall, but retrieval precision degrades quickly as memory volume grows.

Semantically adjacent but irrelevant memories often leak into prompts.

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

## 3. Memory packaging matters more than memory modeling

The biggest gains came from:
- cleaner memory snippets
- reducing retrieval noise
- better context assembly
- concise prompt construction

rather than deeper symbolic structure.

---

## 4. Reranking is fragile

LLM reranking can improve precision, but:
- small local models are unstable rerankers
- aggressive filtering easily removes relevant memories
- semantic drift can become worse instead of better

This remains an active experimentation area.

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

> a practical local memory augmentation layer for LLMs.

---

# Repository Structure

Current implementation intentionally lives mostly in a single file:

```text
main.py
```

This keeps:
- refactoring simple
- global rewrites easy
- debugging transparent
- AI-assisted editing manageable

Future modularization may split:
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

- recover relevant memories from past chats
- avoid unrelated domains
- preserve useful context
- let the downstream LLM combine:
  - retrieved memories
  - general automotive knowledge

into a grounded answer.

The system should not attempt to fully reason beforehand.
Its role is retrieval and packaging.

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
