"""
Local-first conversational memory system for LLMs.

Modes:
- vector-locality: semantic retrieval + locality filtering
- ordered-memory: ordered conversational retrieval using Redis Arrays semantics

Pipeline:
1. Export ChatGPT conversations
2. Extract conversational events
3. Index memories into Redis
4. Retrieve local conversational context
"""

import json
import logging
from pathlib import Path

import argparse
import time
import re

from typing import List

import nltk
from nltk.corpus import stopwords

import numpy as np
import redis
from sentence_transformers import SentenceTransformer
from redis.commands.search.query import Query

# Multilingual stopwords used for lightweight lexical anchoring.
# Falls back gracefully if corpus is missing.
try:
    nltk.data.find("corpora/stopwords")
except LookupError:
    nltk.download("stopwords", quiet=True)

STOPWORDS = set(stopwords.words("italian")) | set(stopwords.words("english"))

GENERIC_PATTERNS = [
    # italian
    "ti spiego",
    "fammi sapere",
    "in generale",
    "dipende",
    "puo essere",
    "potrebbe essere",
    "e importante",
    "bisogna",
    "vediamo",
    # english
    "let me explain",
    "let me know",
    "in general",
    "it depends",
    "could be",
    "might be",
    "it is important",
    "you should",
    "we should",
]

# Long conversations often drift across unrelated topics.
# Memory groups preserve stronger semantic locality during retrieval.

MEMORY_GROUP_SIZE = 12

ORDERED_PREFIX = "arr:chat:"
EVENT_INDEX_PREFIX = "arr:event:"
ORDERED_WINDOW = 3


def parse_message_line(line: str):
    if "|" not in line or ":" not in line:
        return None

    try:
        timestamp_part, rest = line.split("|", 1)
        role_part, content = rest.split(":", 1)

        return {
            "timestamp": timestamp_part.strip(),
            "role": role_part.strip(),
            "content": content.strip(),
        }
    except Exception:
        return None


def ordered_key(chat_id: str):
    return f"{ORDERED_PREFIX}{chat_id}"


def ordered_event_key(anchor):
    normalized = normalize_anchor(anchor)
    return f"{EVENT_INDEX_PREFIX}{normalized}"


def tokenize(text: str):
    words = re.findall(r"\w+", text.lower())
    unique_words = set()

    for word in words:
        if len(word) >= 3 and word not in STOPWORDS and word not in unique_words:
            unique_words.add(word)

    return unique_words


def normalize_anchor(anchor: str):
    anchor = str(anchor or "").lower().strip()

    anchor = anchor.replace(".", "")
    anchor = anchor.replace(",", "")

    anchor = re.sub(r"\s+", "_", anchor)
    anchor = re.sub(r"[^a-z0-9:_-]", "", anchor)

    return anchor


def normalize_numeric_tokens(text: str):
    text = str(text or "")

    matches = re.findall(r"\b\d+[\.,]?\d*\b", text)

    normalized = set()

    for m in matches:
        normalized.add(m)
        normalized.add(m.replace(".", ""))
        normalized.add(m.replace(",", ""))

    return normalized


def extract_anchors(ev: dict):
    anchors = set()

    entity = ev.get("entity")

    if entity:
        if isinstance(entity, list):
            for x in entity:
                if x:
                    anchors.add(normalize_anchor(x))
        else:
            anchors.add(normalize_anchor(entity))

    symptoms = ev.get("symptoms") or []

    if not isinstance(symptoms, list):
        symptoms = [symptoms]

    for s in symptoms:
        for token in tokenize(str(s)):
            anchors.add(normalize_anchor(token))

    tags = ev.get("tags") or []

    if not isinstance(tags, list):
        tags = [tags]

    for t in tags:
        for token in tokenize(str(t)):
            anchors.add(normalize_anchor(token))

    memory_text = ev.get("memory_text") or ""

    for token in tokenize(memory_text):
        anchors.add(normalize_anchor(token))

    cleaned = set()

    for a in anchors:
        if not a:
            continue

        if len(a) <= 2:
            continue

        cleaned.add(a)

    return cleaned


def lexical_overlap_score(query: str, text: str):
    q = tokenize(query)
    t = tokenize(text)

    if not q or not t:
        return 0.0

    overlap = q.intersection(t)

    return len(overlap) / len(q)


class ConversationsExporter:
    """
    Transforms a conversations.json export into individual .txt files.
    """

    def __init__(self, input_file: Path, output_dir: Path):
        self.input_file = input_file
        self.output_dir = output_dir

    def export(self) -> None:
        """Reads conversations.json and writes one .txt file per conversation."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        with self.input_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for conv in data:
            self._export_single(conv)

    def _export_single(self, conv: dict) -> None:
        """Exports a single conversation to a .txt file."""
        chat_id = conv.get("id", "unknown")
        mapping = conv.get("mapping", {})

        nodes = sorted(
            mapping.values(),
            key=lambda n: (
                (n.get("message") or {}).get("create_time") or n.get("create_time") or 0
            ),
        )

        messages = []
        for node in nodes:
            msg = node.get("message")
            if not msg:
                continue

            author = msg.get("author", {}).get("role")

            timestamp = msg.get("create_time") or node.get("create_time") or ""

            content_obj = msg.get("content") or {}
            parts = content_obj.get("parts") or []

            # normalize parts to list[str]
            content = []
            for p in parts:
                if isinstance(p, str):
                    content.append(p)
                elif isinstance(p, dict):
                    # handle structured content if present
                    text = p.get("text")
                    if isinstance(text, str):
                        content.append(text)

            if author and content:
                text = " ".join(content)
                messages.append(f"{timestamp} | {author.upper()}: {text}")

        output_path = self.output_dir / f"{chat_id}.txt"
        with output_path.open("w", encoding="utf-8") as f:
            f.write("\n\n".join(messages))

        logger.info("Exported chucnks for chat %s → %s", chat_id, output_path)


logger = logging.getLogger(__name__)

# -----------------------
# INDEX LAYER (REDIS VECTOR DB)
# -----------------------

REDIS_HOST = "localhost"
REDIS_PORT = 6379

# Arrays/ARGREP support currently requires Redis unstable branch.
# Current implementation emulates ordered memory semantics using Lists.
REDIS_UNSTABLE_IMAGE = "redis-unstable-arrays"

INDEX_NAME = "idx:memory"
PREFIX = "mem:"

EMBED_DIM = 384

# default dirs (can be overridden via CLI)
CHUNKS_DIR = Path("./data/chunks")
EVENTS_DIR = Path("./data/events")

MODEL = None


def get_model():
    """Lazy load embedding model to avoid repeated initialization."""
    global MODEL
    if MODEL is None:
        MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return MODEL


redis_instance = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)


def run_ollama(prompt: str, model: str = "phi3:latest") -> str:
    """
    Sends prompt to local Ollama and returns the generated response.
    """
    import requests

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        logger.error("Ollama inference error: %s", e)
        return ""


def create_index():
    """Create Redis vector index if not existing."""
    try:
        redis_instance.ft(INDEX_NAME).info()
        logger.info("Index already exists")
        return
    except Exception:
        pass

    schema = [
        "ON",
        "HASH",
        "PREFIX",
        "1",
        PREFIX,
        "SCHEMA",
        "content",
        "TEXT",
        "chat_id",
        "TAG",
        "memory_group",
        "TAG",
        "doc_type",
        "TAG",
        "entity",
        "TEXT",
        "embedding",
        "VECTOR",
        "HNSW",
        "6",
        "TYPE",
        "FLOAT32",
        "DIM",
        EMBED_DIM,
        "DISTANCE_METRIC",
        "COSINE",
    ]

    logger.info("Creating index with name %s", INDEX_NAME)
    redis_instance.execute_command("FT.CREATE", INDEX_NAME, *schema)
    logger.info("Index created")


def embed(text: str) -> bytes:
    """Generate embedding for text."""
    vec = get_model().encode(text, show_progress_bar=False)
    return np.array(vec, dtype=np.float32).tobytes()


def store_doc(key: str, fields: dict):
    """Store document in Redis. Ensures all values are valid Redis types."""
    cleaned = {}
    for k, v in fields.items():
        if isinstance(v, (str, bytes, int, float)):
            cleaned[k] = v
        else:
            # fallback: serialize complex types (list, dict, etc.)
            try:
                cleaned[k] = json.dumps(v)
            except Exception:
                cleaned[k] = str(v)

    redis_instance.hset(key, mapping=cleaned)


# ---------- Ordered Memory Functions ----------


def store_ordered_conversation(chat_id: str, messages: List[dict]):
    key = ordered_key(chat_id)

    redis_instance.delete(key)

    pipe = redis_instance.pipeline()

    for idx, msg in enumerate(messages):
        payload = json.dumps(
            {
                "index": idx,
                "timestamp": msg["timestamp"],
                "role": msg["role"],
                "content": msg["content"],
            },
            ensure_ascii=False,
        )

        pipe.rpush(key, payload)

    pipe.execute()


def store_ordered_event(anchor: str, chat_id: str, message_index: int):
    if not anchor:
        return

    key = ordered_event_key(anchor)

    redis_instance.rpush(
        key,
        json.dumps(
            {
                "chat_id": chat_id,
                "message_index": message_index,
            }
        ),
    )


def index_ordered_conversations(chunks_dir: Path = CHUNKS_DIR):
    for file in chunks_dir.glob("*.txt"):
        chat_id = file.stem
        text = file.read_text(encoding="utf-8")

        messages = []

        for raw in text.split("\n\n"):
            parsed = parse_message_line(raw.strip())

            if not parsed:
                continue

            messages.append(parsed)

        if not messages:
            continue

        store_ordered_conversation(chat_id, messages)

        logger.info(
            "Indexed ordered conversation %s (%d messages)", chat_id, len(messages)
        )


def index_ordered_events(events_dir: Path = EVENTS_DIR):
    for file in events_dir.glob("*.json"):
        chat_id = file.stem
        raw = json.loads(file.read_text(encoding="utf-8"))

        if isinstance(raw, dict) and "events" in raw:
            data = raw["events"]
        elif isinstance(raw, list):
            data = raw
        else:
            continue

        for ev in data:
            if not isinstance(ev, dict):
                continue

            anchors = extract_anchors(ev)
            timestamps = ev.get("timestamp") or []

            if isinstance(timestamps, str):
                timestamps = [timestamps]

            for ts in timestamps:
                try:
                    ts = str(ts).strip()
                except Exception:
                    continue

                key = ordered_key(chat_id)
                messages = redis_instance.lrange(key, 0, -1)

                for idx, raw_msg in enumerate(messages):
                    try:
                        msg = json.loads(raw_msg)
                    except Exception:
                        continue

                    if str(msg.get("timestamp", "")).startswith(ts):
                        for anchor in anchors:
                            store_ordered_event(anchor, chat_id, idx)
                        break

        logger.info("Indexed ordered events for %s", chat_id)


def ordered_expand(chat_id: str, index: int, window: int = ORDERED_WINDOW):
    key = ordered_key(chat_id)

    start = max(0, index - window)
    end = index + window

    items = redis_instance.lrange(key, start, end)

    parsed = []

    for item in items:
        try:
            parsed.append(json.loads(item))
        except Exception:
            continue

    return parsed


def ordered_argrep(query: str, max_results: int = 5):
    ordered_hits = []
    seen = set()

    query_terms = tokenize(query)

    for key in redis_instance.scan_iter(f"{ORDERED_PREFIX}*"):
        chat_id = key.decode().replace(ORDERED_PREFIX, "")

        messages = redis_instance.lrange(key, 0, -1)

        for idx, raw_msg in enumerate(messages):
            try:
                msg = json.loads(raw_msg)
            except Exception:
                continue

            content = str(msg.get("content", ""))
            lowered = content.lower()
            numeric_tokens = normalize_numeric_tokens(content)

            lexical_match = any(term in lowered for term in query_terms)

            numeric_match = False

            for q in query_terms:
                q_norm = q.replace(".", "").replace(",", "")

                if q_norm in numeric_tokens:
                    numeric_match = True
                    break

            if not lexical_match and not numeric_match:
                continue

            dedup = f"{chat_id}:{idx}"

            if dedup in seen:
                continue

            seen.add(dedup)

            ordered_hits.append(
                {
                    "chat_id": chat_id,
                    "message_index": idx,
                    "score": sum(1 for t in query_terms if t in lowered),
                    "anchor_message": msg,
                    "context": ordered_expand(chat_id, idx),
                }
            )

    ordered_hits = sorted(
        ordered_hits,
        key=lambda x: x["score"],
        reverse=True,
    )

    return ordered_hits[:max_results]


def ordered_search(query: str, max_results: int = 5):
    ordered_hits = []
    seen = set()

    query_terms = tokenize(query)

    for key in redis_instance.scan_iter(f"{ORDERED_PREFIX}*"):
        chat_id = key.decode().replace(ORDERED_PREFIX, "")

        messages = redis_instance.lrange(key, 0, -1)

        for idx, raw_msg in enumerate(messages):
            try:
                msg = json.loads(raw_msg)
            except Exception:
                continue

            content = str(msg.get("content", ""))
            lowered = content.lower()

            lexical_hits = 0

            for term in query_terms:
                if term in lowered:
                    lexical_hits += 1
                    continue

                normalized_term = term.replace(".", "").replace(",", "")

                if normalized_term in numeric_tokens:
                    lexical_hits += 1

            if lexical_hits == 0:
                continue

            dedup = f"{chat_id}:{idx}"

            if dedup in seen:
                continue

            seen.add(dedup)

            context = ordered_expand(chat_id, idx)

            ordered_hits.append(
                {
                    "chat_id": chat_id,
                    "message_index": idx,
                    "score": lexical_hits,
                    "anchor_message": msg,
                    "context": context,
                }
            )

    ordered_hits = sorted(
        ordered_hits,
        key=lambda x: x["score"],
        reverse=True,
    )

    return ordered_hits[:max_results]


def build_ordered_context(results):
    blocks = []

    for hit in results:
        lines = []

        anchor = hit.get("anchor_message") or {}
        anchor_role = anchor.get("role", "UNKNOWN")
        anchor_content = anchor.get("content", "").strip()

        if anchor_content:
            lines.append("ANCHOR MESSAGE:")
            lines.append(f"{anchor_role}: {anchor_content}")
            lines.append("")
            lines.append("LOCAL CONTEXT:")

        for msg in hit["context"]:
            role = msg.get("role", "UNKNOWN")
            content = msg.get("content", "").strip()

            if not content:
                continue

            if content == anchor_content:
                continue

            lines.append(f"{role}: {content}")

        if not lines:
            continue

        block = (
            f"CHAT: {hit['chat_id']}\n"
            f"MATCH SCORE: {hit['score']}\n" + "\n".join(lines)
        )

        blocks.append(block)

    return "\n\n---\n\n".join(blocks)


def index_chunks(chunks_dir: Path = CHUNKS_DIR):
    """Index chunk text files."""
    for file in chunks_dir.glob("*.txt"):
        chat_id = file.stem
        text = file.read_text()

        parts = text.split("\n\n")

        for i, chunk in enumerate(parts):
            logger.info("Indexing chunk %s #%d", chat_id, i)
            group_id = i // MEMORY_GROUP_SIZE
            memory_group = f"{chat_id}:g{group_id}"

            chunk = chunk.strip()

            if not chunk:
                continue

            if len(chunk.split()) < 8:
                continue

            normalized = chunk.lower()

            if any(pattern in normalized for pattern in GENERIC_PATTERNS):
                continue

            key = f"{PREFIX}chunk:{chat_id}:{i}"

            store_doc(
                key,
                {
                    "content": chunk,
                    "chat_id": chat_id,
                    "memory_group": memory_group,
                    "doc_type": "chunk",
                    "entity": "",
                    "embedding": embed(chunk),
                },
            )

        logger.info("Indexed chunks for %s", chat_id)


def index_events(events_dir: Path = EVENTS_DIR):
    """Index event JSON files."""
    for file in events_dir.glob("*.json"):
        chat_id = file.stem
        raw = json.loads(file.read_text())

        if isinstance(raw, dict) and "events" in raw:
            data = raw["events"]
        elif isinstance(raw, list):
            data = raw
        else:
            logger.warning("Unexpected format in %s, skipping", file)
            continue

        for i, ev in enumerate(data):
            if not isinstance(ev, dict):
                continue

            group_id = i // MEMORY_GROUP_SIZE
            memory_group = f"{chat_id}:g{group_id}"
            entity = ev.get("entity", "") or ""
            ev_type = ev.get("type", "") or ""
            symptoms = ev.get("symptoms", []) or []
            if not isinstance(symptoms, list):
                symptoms = [symptoms]
            symptoms = [str(s) for s in symptoms if s is not None]

            tags = ev.get("tags", []) or []
            if not isinstance(tags, list):
                tags = [tags]
            tags = [str(t) for t in tags if t is not None]

            memory_text = ev.get("memory_text", "") or ""

            text = memory_text.strip()

            if not text:
                text = f"""
                {entity}
                {' '.join(symptoms)}
                {' '.join(tags)}
                """.strip()

            if not text:
                continue

            key = f"{PREFIX}event:{chat_id}:{i}"
            logger.info("Indexing event %s #%d (%s)", chat_id, i, entity)
            store_doc(
                key,
                {
                    "content": text,
                    "chat_id": chat_id,
                    "memory_group": memory_group,
                    "doc_type": "event",
                    "entity": entity,
                    "embedding": embed(text),
                },
            )

        logger.info("Indexed events for %s", chat_id)


def search(query: str, k: int = 15):
    """Search chunks + events grouped by chat_id."""
    q_vec = embed(query)

    def run_query(filter_query):
        def _decode(x):
            if isinstance(x, bytes):
                return x.decode("utf-8")
            return x

        q = (
            Query(f"{filter_query}=>[KNN {k} @embedding $vec AS score]")
            .return_fields(
                "content",
                "chat_id",
                "memory_group",
                "doc_type",
                "entity",
                "score",
            )
            .sort_by("score")
            .dialect(2)
        )
        res = redis_instance.ft(INDEX_NAME).search(q, query_params={"vec": q_vec})
        docs = getattr(res, "docs", [])
        filtered = []

        for d in docs:
            content = _decode(d.content)
            overlap = lexical_overlap_score(query, content)

            doc_type = _decode(d.doc_type)
            score = float(d.score)

            if doc_type == "event":
                # Events are compressed semantic memories.
                # Retrieval stays intentionally permissive because
                # event embeddings are denser and noisier than chunks.
                if score < 0.78:
                    filtered.append(d)

            else:
                if overlap >= 0.20 or score < 0.55:
                    filtered.append(d)

        return filtered

    chunk_docs = run_query("@doc_type:{chunk}")
    event_docs = run_query("@doc_type:{event}")

    docs = chunk_docs + event_docs

    grouped = {}

    def _decode(x):
        if isinstance(x, bytes):
            return x.decode("utf-8")
        return x

    for doc in docs:
        chat_id = _decode(doc.chat_id)
        memory_group = _decode(doc.memory_group)

        group_key = memory_group or chat_id

        if group_key not in grouped:
            grouped[group_key] = {
                "chat_id": chat_id,
                "memory_group": group_key,
                "chunks": [],
                "events": [],
            }

        item = {
            "content": _decode(doc.content),
            "entity": _decode(doc.entity) if doc.entity else "",
            "score": float(doc.score),
        }

        doc_type = _decode(doc.doc_type)

        if doc_type == "event":
            grouped[group_key]["events"].append(item)
        else:
            grouped[group_key]["chunks"].append(item)

    for chat in grouped.values():
        event_scores = [x["score"] for x in chat["events"]]
        chunk_scores = [x["score"] for x in chat["chunks"]]

        event_component = min(event_scores) if event_scores else 999

        chunk_component = (
            sum(sorted(chunk_scores)[:3]) / min(len(chunk_scores), 3)
            if chunk_scores
            else 999
        )

        # Events benefit from best-match scoring because they are sparse.
        # Chunks instead benefit from averaging because they are noisier.
        chat["score"] = min(
            event_component * 0.75,
            chunk_component,
        )

    # lower score is better
    results = sorted(grouped.values(), key=lambda x: x["score"])
    return results[:10]


# --------------------------------
# Context and Prompt Builders
# --------------------------------
def build_context(results):
    """
    Builds a compact memory-oriented context block.

    Responsibilities:
    - merges retrieved memories from multiple relevant chats
    - prioritizes high-signal events over raw chunks
    - packages memories in dense natural-language form
    - reduces prompt noise before LLM generation
    """
    if not results:
        return ""

    # Select only semantically local memory groups.
    MAX_CHATS = 5
    # Wider windows preserve nearby episodic memories.
    SCORE_WINDOW = 0.35

    best_score = results[0].get("score", 999)

    selected_chats = []
    selected_memory_groups = set()

    for chat in results:
        if len(selected_chats) >= MAX_CHATS:
            break

        score = chat.get("score", 999)

        # Lower cosine distance is better.
        if abs(score - best_score) <= SCORE_WINDOW:
            memory_group = chat.get("memory_group")

            if memory_group in selected_memory_groups:
                continue

            selected_memory_groups.add(memory_group)
            selected_chats.append(chat)

    # --- Merge and globally rerank retrieved memories
    all_events = []
    all_chunks = []

    for chat in selected_chats:
        # Preserve retrieved episodic memories.
        all_events.extend(chat["events"])

        # Chunks provide supporting conversational context.
        all_chunks.extend(chat["chunks"])

    # lower score is better
    all_events = sorted(all_events, key=lambda x: x["score"])
    all_chunks = sorted(all_chunks, key=lambda x: x["score"])

    # --- Deduplicate events
    events_text = []
    seen_events = set()

    for ev in all_events:
        memory = ev["content"].strip()

        if not memory:
            continue

        normalized = memory.lower().strip()

        if normalized in seen_events:
            continue

        seen_events.add(normalized)
        events_text.append(f"- {memory}")

        if len(events_text) >= 8:
            break

    # --- Compress chunks
    chunks_text = []
    seen_chunks = set()

    for ch in all_chunks:
        content = ch["content"].strip()

        if not content:
            continue

        # remove timestamp prefixes
        if "| USER:" in content or "| ASSISTANT:" in content:
            parts = content.split(":", 1)
            if len(parts) == 2:
                content = parts[1].strip()

        # remove noisy citations
        content = content.replace("citeturn0search2", "")

        normalized = content.lower().strip()

        if normalized in seen_chunks:
            continue

        seen_chunks.add(normalized)
        chunks_text.append(f"- {content}")

        if len(chunks_text) >= 5:
            break

    block = f"""
EVENTS:
{chr(10).join(events_text) if events_text else "None"}

CONTEXT:
{chr(10).join(chunks_text) if chunks_text else "None"}
"""

    return block.strip()


def build_prompt(user_query: str, context: str) -> str:
    """
    Build final prompt for LLM using retrieved context.
    """
    return f"""
You are an assistant with access to retrieved long-term memory.

Your task:
Answer the user's question using:
1. Retrieved memories when relevant
2. General knowledge when memories are incomplete

---

RETRIEVED MEMORIES:
{context}

---

USER QUESTION:
{user_query}

---

INSTRUCTIONS:
- Retrieved messages preserve original conversational locality
- ANCHOR MESSAGE is the primary retrieval hit
- LOCAL CONTEXT contains adjacent conversational turns
- Prioritize concrete facts explicitly stated in the ANCHOR MESSAGE
- Use LOCAL CONTEXT only to reconstruct surrounding meaning
- Do not average or merge unrelated medical facts
- If a number, date, or diagnosis is explicitly present, prefer exact retrieval over summarization
- If multiple conflicting memories exist, say so explicitly
- Preserve numbers exactly as written in retrieved memory
- Answer the user's actual retrieval question directly and briefly
"""


# --------------------------------
# Index cleanup helper
# --------------------------------
def cleanup_index():
    """
    Removes all indexed data and drops the Redis index.
    Safe reset before re-indexing.
    """
    try:
        logger.info("Starting the Redis cleanup process.")
        redis_instance.execute_command("FT.DROPINDEX", INDEX_NAME, "DD")
        logger.info("Dropped index %s and all associated documents", INDEX_NAME)
    except Exception as e:
        logger.warning("Index drop failed or does not exist: %s", e)

    try:
        keys = redis_instance.keys(f"{PREFIX}*")
        if keys:
            redis_instance.delete(*keys)
            logger.info("Deleted %d leftover keys", len(keys))
    except Exception as e:
        logger.warning("Error deleting keys: %s", e)


class EventCreator:
    """
    Generates structured event JSON files from conversation .txt files using OpenAI.
    """

    SYSTEM_PROMPT = """
You are a structured information extraction engine.

INPUT:
A conversation composed of timestamped messages:
<timestamp> | ROLE: text

TASK:
Extract ALL atomic concrete, factual information and events present in the conversation.
You MUST extract MULTIPLE events when multiple facts exist. Do NOT summarize into a single event.


A fact is:
- a result, finding, condition, measurement, statement, decision, or recommendation
- something specific and attributable to an entity

OUTPUT:
Return ONLY a valid JSON array of objects.

Each object MUST have EXACTLY this structure:
{
  "entity": "<what the fact is about>",
  "type": "<short label describing what kind of fact this is>",
  "symptoms": ["<specific details, measurements, descriptors>"],
  "tags": ["<contextual labels>"],
  "memory_text": "<short natural language memory optimized for future retrieval>",
  "timestamp": ["<one or more timestamps from the conversation>"]
}

STRICT RULES:
- entity MUST be non-empty
- type MUST be non-empty
- memory_text MUST be non-empty
- memory_text MUST be a short natural-language sentence
- memory_text MUST summarize the fact in retrieval-friendly form
- timestamp MUST always be a list of strings
- DO NOT output null values
- DO NOT output empty objects
- DO NOT output generic placeholders
- Each event MUST correspond to a specific fact (never aggregate multiple facts into one)
- You MUST extract AS MANY events as there are distinct facts
- timestamp MUST be copied EXACTLY from the input messages (do not invent or transform)

EXTRACTION RULES:
- Extract atomic facts (split multiple facts into separate objects)
- Prefer specific entities (e.g. organs, systems, objects, people, concepts)
- Include measurements, quantities, and descriptors in symptoms
- Use tags to capture context (e.g. benign, followup, risk, normal)
- If no facts are present, return []
- For each extracted fact, attach the timestamp(s) of the message(s) where that fact appears
- If a fact comes from a single message, use exactly that message timestamp
- memory_text should read like a compact memory the assistant could reuse later
- memory_text should avoid JSON-like formatting and field repetition

OUTPUT CONSTRAINTS:
- Output ONLY JSON
- No text before or after
"""

    def __init__(self, input_dir: Path, output_dir: Path, model: str):
        """
        :param input_dir: Directory containing .txt conversations
        :param output_dir: Directory where JSON event files will be saved
        :param model: OpenAI model name
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.model = model
        # self.use_ollama = os.getenv("USE_OLLAMA") == "1"
        self.use_ollama = True

        if self.use_ollama:
            self.model = (
                model
                if model
                in [
                    "phi3",
                    "phi3:latest",
                    "llama3",
                    "llama3:latest",
                    "mistral",
                    "mistral:latest",
                ]
                else "phi3:latest"
            )

    def _split_into_chunks(self, text: str, max_chars: int = 20000):
        """
        Splits conversation text into chunks, preserving message boundaries.
        """
        parts = text.split("\n\n")

        chunks = []
        current = []
        current_len = 0

        for part in parts:
            part_len = len(part)

            if current_len + part_len > max_chars and current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0

            current.append(part)
            current_len += part_len

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    def process_all(self) -> None:
        """
        Processes all .txt files in input_dir.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        files = list(self.input_dir.glob("*.txt"))
        total = len(files)
        logger.info("Found %d files to process", total)

        for i, file_path in enumerate(files, start=1):
            logger.info("[%d/%d] Processing %s", i, total, file_path.name)
            self._process_single(file_path)

    def _process_single(self, file_path: Path) -> None:
        """
        Processes a single conversation file and writes its events JSON.
        """
        chat_id = file_path.stem
        text = file_path.read_text(encoding="utf-8")

        logger.debug("Read %s (%d chars)", chat_id, len(text))

        if self.use_ollama:
            chunks = self._split_into_chunks(text, max_chars=20000)
            all_events = []

            for idx, chunk in enumerate(chunks):
                logger.info(
                    "Processing chunk %d/%d for %s", idx + 1, len(chunks), chat_id
                )
                data = self._process_with_ollama(chunk, chat_id)
                if data is None:
                    continue
                data = self._sanitize_events(data)

                # compute fallback day-level timestamps from role-tagged lines only
                import re
                from datetime import datetime

                # match only valid message lines: TIMESTAMP | ROLE:
                pattern = re.compile(
                    r"(?m)^\s*(\d{9,}(?:\.\d+)?)\s*\|\s*(SYSTEM|USER|ASSISTANT)\s*:"
                )
                matches = pattern.findall(chunk)

                fallback_dates = []
                for ts, _role in matches:
                    try:
                        dt = datetime.fromtimestamp(float(ts))
                        day = dt.strftime("%Y-%m-%d")
                        # append only when day changes
                        if not fallback_dates or fallback_dates[-1] != day:
                            fallback_dates.append(day)
                    except Exception:
                        continue

                # assign fallback only if missing, using first day (coarse anchoring)
                if fallback_dates:
                    for ev in data:
                        ts = ev.get("timestamp")
                        if not ts:
                            ev["timestamp"] = [fallback_dates[0]]

                all_events.extend(data)

            self._write_output(chat_id, all_events)
            return

        logger.error("OpenAI path disabled. USE_OLLAMA must be enabled.")
        return

    def _process_with_ollama(self, text: str, chat_id: str):
        """
        Uses Ollama local model to extract events.
        """
        import requests

        logger.debug("Sending request to Ollama for %s (model=%s)", chat_id, self.model)
        start_ts = time.time()

        try:
            # DO NOT truncate blindly — preserve full conversation for extraction
            # If needed, only trim extremely large inputs

            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": self.model,
                    "prompt": self.SYSTEM_PROMPT + "\n\nCONVERSATION:\n" + text,
                    "stream": False,
                    "format": "json",
                },
                timeout=60,
            )
            response.raise_for_status()

            elapsed = time.time() - start_ts
            logger.info(
                "Ollama responded for %s in %.2fs (status=%s)",
                chat_id,
                elapsed,
                response.status_code,
            )

            output = response.json().get("response", "").strip()

            # try direct JSON parse first
            try:
                data = json.loads(output)
                logger.debug("Parsed JSON successfully for %s", chat_id)
                return data
            except Exception:
                pass

            # fallback: extract JSON array
            start = output.find("[")
            end = output.rfind("]")
            if start != -1 and end != -1:
                candidate = output[start : end + 1]
                try:
                    data = json.loads(candidate)
                    logger.debug("Parsed JSON successfully for %s", chat_id)
                    return data
                except Exception:
                    pass

            logger.error(
                "Failed to parse JSON for %s. Raw output (truncated): %s",
                chat_id,
                output[:500],
            )
            return None
        except Exception as e:
            logger.error("Ollama error for %s: %s", chat_id, e)
            return None

    def _write_output(self, chat_id: str, data):
        """
        Writes event JSON to file.
        """
        output_file = self.output_dir / f"{chat_id}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug(
            "Writing %s (%d events)",
            chat_id,
            len(data) if isinstance(data, list) else -1,
        )
        logger.info("Processed %s → %s", chat_id, output_file)

    def _sanitize_events(self, data):
        """
        Cleans and normalizes model output.

        Responsibilities:
        - removes invalid events
        - normalizes timestamp to list[str]
        - preserves memory_text when available
        - drops malformed objects
        - ensures downstream indexing stability
        """
        # Handle cases where model returns an object instead of a list
        if isinstance(data, dict):
            # common pattern: {"events": [...]}
            if "events" in data and isinstance(data["events"], list):
                data = data["events"]
            else:
                # try to wrap single event into list
                data = [data]

        if not isinstance(data, list):
            logger.warning("Unexpected data format, skipping: %s", type(data))
            return []

        cleaned = []
        for ev in data:
            if not isinstance(ev, dict):
                continue

            entity = ev.get("entity")
            ev_type = ev.get("type")
            symptoms = ev.get("symptoms") or []
            tags = ev.get("tags") or []
            memory_text = ev.get("memory_text") or ""
            timestamp = ev.get("timestamp")

            # drop useless events
            if not entity or not ev_type:
                continue

            # fallback memory synthesis if model omitted it
            if not memory_text:
                parts = []

                if entity:
                    parts.append(str(entity))

                if symptoms:
                    if isinstance(symptoms, list):
                        parts.append(", ".join(str(x) for x in symptoms if x))
                    else:
                        parts.append(str(symptoms))

                if tags:
                    if isinstance(tags, list):
                        parts.append("(" + ", ".join(str(x) for x in tags if x) + ")")
                    else:
                        parts.append(f"({tags})")

                memory_text = " ".join(parts).strip()

            # normalize timestamp
            if isinstance(timestamp, str) and timestamp.strip():
                timestamp = [timestamp.strip()]
            elif isinstance(timestamp, list):
                timestamp = [str(t).strip() for t in timestamp if str(t).strip()]
            else:
                # fallback: try to extract timestamp from symptoms text if model missed it
                timestamp = []

            # keep events even if timestamp missing (will be filled later)
            if not timestamp:
                timestamp = []

            cleaned.append(
                {
                    "entity": entity,
                    "type": ev_type,
                    "symptoms": symptoms,
                    "tags": tags,
                    "memory_text": memory_text,
                    "timestamp": timestamp,
                    **(
                        {"attributes": ev.get("attributes")}
                        if "attributes" in ev
                        else {}
                    ),
                }
            )

        return cleaned


def setup_logging() -> None:
    """Configures root logger."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--input", required=True)
    export_parser.add_argument("--output", required=True)

    events_parser = subparsers.add_parser("events")
    events_parser.add_argument("--input", required=True)
    events_parser.add_argument("--output", required=True)
    events_parser.add_argument("--model", default="gpt-5.4-mini")

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--chunks", required=True)
    index_parser.add_argument("--events", required=True)
    index_parser.add_argument(
        "--mode",
        choices=["vector", "ordered", "hybrid"],
        default="vector",
    )

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument(
        "--mode",
        choices=["vector", "ordered", "argrep"],
        default="vector",
    )
    search_parser.add_argument(
        "--ollama",
        action="store_true",
        help="Send generated prompt to Ollama and print response",
    )
    search_parser.add_argument(
        "--ollama-model",
        default="phi3:latest",
        help="Ollama model to use",
    )

    cleanup_parser = subparsers.add_parser("cleanup")

    args = parser.parse_args()

    setup_logging()

    base_dir = Path.cwd()

    input_path = None
    output_path = None

    if hasattr(args, "input") and args.input:
        input_path = (
            (base_dir / args.input).resolve()
            if not Path(args.input).is_absolute()
            else Path(args.input)
        )

    if hasattr(args, "output") and args.output:
        output_path = (
            (base_dir / args.output).resolve()
            if not Path(args.output).is_absolute()
            else Path(args.output)
        )

    if input_path:
        logger.info("Resolved input path: %s", input_path)
    if output_path:
        logger.info("Resolved output path: %s", output_path)

    if args.command == "export":
        if not input_path or not output_path:
            raise ValueError("export requires --input and --output")

        exporter = ConversationsExporter(
            input_file=input_path,
            output_dir=output_path,
        )
        exporter.export()

    elif args.command == "events":
        if not input_path or not output_path:
            raise ValueError("events requires --input and --output")

        creator = EventCreator(
            input_dir=input_path,
            output_dir=output_path,
            model=args.model,
        )
        creator.process_all()

    elif args.command == "index":
        if args.mode in ["vector", "hybrid"]:
            create_index()
            index_chunks(Path(args.chunks))
            index_events(Path(args.events))

        if args.mode in ["ordered", "hybrid"]:
            index_ordered_conversations(Path(args.chunks))
            index_ordered_events(Path(args.events))

    elif args.command == "search":
        if args.mode == "ordered":
            results = ordered_search(args.query)
            context = build_ordered_context(results)

        elif args.mode == "argrep":
            results = ordered_argrep(args.query)
            context = build_ordered_context(results)

        else:
            results = search(args.query)
            context = build_context(results)

        prompt = build_prompt(args.query, context)

        print("\n===== CONTEXT =====\n")
        print(context)

        print("\n===== PROMPT =====\n")
        print(prompt)

        if args.ollama:
            print("\n===== OLLAMA RESPONSE =====\n")
            answer = run_ollama(prompt, model=args.ollama_model)
            print(answer)

    elif args.command == "cleanup":
        cleanup_index()


if __name__ == "__main__":
    main()
