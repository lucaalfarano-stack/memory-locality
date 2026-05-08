"""
CLI entry point for the events-extractor project.

This tool provides an end-to-end pipeline to:
1. Export conversations from ChatGPT export format into text chunks
2. Extract structured events from those conversations using a local LLM (Ollama)
3. Index both chunks and events into a Redis vector database
4. Perform semantic search across conversations (mixed retrieval: chunks + events)

Commands:

- export:
    Convert a conversations.json file into one .txt file per conversation.

- events:
    Generate structured event JSON files from .txt conversations using Ollama.

- index:
    Index chunks and events into Redis (vector + metadata).

- search:
    Perform semantic search over indexed data and return grouped results by conversation.

- cleanup:
    Drop Redis index and delete all stored documents (mem:*).

Examples:

# 1. Export conversations → chunks
python main.py export \
  --input ./data/raw/conversations.json \
  --output ./data/chunks

# 2. Generate events from chunks
python main.py events \
  --input ./data/chunks \
  --output ./data/events

# 3. Index chunks + events into Redis
python main.py index \
  --chunks ./data/chunks \
  --events ./data/events

# 4. Search across indexed data
python main.py search \
  --query "jenkins logs error count"

# 5. Cleanup Redis index and stored data
python main.py cleanup

Notes:
- Paths are resolved relative to the current working directory.
- Requires a running Redis instance with RediSearch (e.g. redis-stack).
- Requires Ollama running locally (default: http://localhost:11434).
- No OpenAI API is required.
- Indexing is append-only unless explicitly cleaned.
"""

import json
import logging
from pathlib import Path

import argparse
import time

# --- Added imports for index layer ---
import numpy as np
import redis
from sentence_transformers import SentenceTransformer
from redis.commands.search.query import Query


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


def index_chunks(chunks_dir: Path = CHUNKS_DIR):
    """Index chunk text files."""
    for file in chunks_dir.glob("*.txt"):
        chat_id = file.stem
        text = file.read_text()

        parts = text.split("\n\n")

        for i, chunk in enumerate(parts):
            logger.info("Indexing chunk %s #%d", chat_id, i)
            if not chunk.strip():
                continue

            key = f"{PREFIX}chunk:{chat_id}:{i}"

            store_doc(
                key,
                {
                    "content": chunk,
                    "chat_id": chat_id,
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
                    "doc_type": "event",
                    "entity": entity,
                    "embedding": embed(text),
                },
            )

        logger.info("Indexed events for %s", chat_id)


def search(query: str, k=15):
    """Search chunks + events grouped by chat_id."""
    q_vec = embed(query)

    k = 15

    def run_query(filter_query):
        q = (
            Query(f"{filter_query}=>[KNN {k} @embedding $vec AS score]")
            .return_fields("content", "chat_id", "doc_type", "entity", "score")
            .sort_by("score")
            .dialect(2)
        )
        res = redis_instance.ft(INDEX_NAME).search(q, query_params={"vec": q_vec})
        return getattr(res, "docs", [])

    chunk_docs = run_query("@doc_type:{chunk}")
    event_docs = run_query("@doc_type:{event}")

    docs = chunk_docs + event_docs

    def _decode(x):
        if isinstance(x, bytes):
            return x.decode("utf-8")
        return x

    grouped = {}

    for doc in docs:
        chat_id = _decode(doc.chat_id)

        if chat_id not in grouped:
            grouped[chat_id] = {"chat_id": chat_id, "chunks": [], "events": []}

        item = {
            "content": _decode(doc.content),
            "entity": _decode(doc.entity) if doc.entity else "",
            "score": float(doc.score),
        }

        doc_type = _decode(doc.doc_type)

        if doc_type == "event":
            grouped[chat_id]["events"].append(item)
        else:
            grouped[chat_id]["chunks"].append(item)

    for chat in grouped.values():
        event_scores = [x["score"] for x in chat["events"]]
        chunk_scores = [x["score"] for x in chat["chunks"]]

        best_event = min(event_scores) if event_scores else 999
        best_chunk = min(chunk_scores) if chunk_scores else 999

        # events are higher signal than chunks
        # lower Redis cosine distance is better
        chat["score"] = min(best_event * 0.8, best_chunk)

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

    # --- Select only chats within a relevance window
    MAX_CHATS = 5
    SCORE_WINDOW = 0.12

    best_score = results[0].get("score", 999)

    selected_chats = []

    for chat in results:
        if len(selected_chats) >= MAX_CHATS:
            break

        score = chat.get("score", 999)

        # lower score is better (cosine distance)
        if abs(score - best_score) <= SCORE_WINDOW:
            selected_chats.append(chat)

    # --- Merge and globally rerank retrieved memories
    all_events = []
    all_chunks = []

    for chat in selected_chats:
        all_events.extend(chat["events"])
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
- EVENTS are higher-confidence memories
- CONTEXT messages are supporting evidence only
- Ignore memories that appear unrelated to the question
- Do NOT connect unrelated memories together
- Do NOT invent causal relationships unless explicitly supported
- If memories are insufficient, rely on general knowledge
- Clearly distinguish:
  • what is known from memory
  • what comes from general knowledge
- Be concise, practical, and grounded
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

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
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
        create_index()
        index_chunks(Path(args.chunks))
        index_events(Path(args.events))

    elif args.command == "search":
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
