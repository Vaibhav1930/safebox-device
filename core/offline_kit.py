import json
import os
import re
from pathlib import Path
from core.logger import get_logger

log = get_logger("offline_kit")

# offline_kit lives in the project root — not on the SSD vault path
KIT_ROOT = Path(__file__).resolve().parents[1] / "offline_kit"
INDEX_PATH = KIT_ROOT / "index.json"
DOCS_PATH = KIT_ROOT / "docs"

SECTION_SPLIT = "\n\n"

MIN_DOC_SCORE = int(os.getenv("OFFLINE_KIT_MIN_DOC_SCORE", "6"))
MIN_SECTION_SCORE = int(os.getenv("OFFLINE_KIT_MIN_SECTION_SCORE", "3"))

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "case",
    "could", "do", "does", "for", "from", "give", "how", "i", "in",
    "is", "it", "me", "my", "of", "on", "or", "please", "tell",
    "the", "this", "to", "what", "when", "where", "who", "why",
    "with", "you", "your",
}

UTILITY_QUERY_PATTERNS = [
    r"\bwhat time\b",
    r"\bcurrent time\b",
    r"\btell me the time\b",
    r"\bwhat is the time\b",
    r"\btemperature\b",
    r"\bdevice status\b",
    r"\bsystem status\b",
    r"\bbattery\b",
    r"\bplug\b",
    r"\block\b",
    r"\bunlock\b",
]

DOC_DOMAIN_KEYWORDS = {
    "first_aid": {
        "cpr", "first", "aid", "bleed", "bleeding", "blood", "burn",
        "fracture", "choke", "choking", "fever", "dehydration",
        "emergency", "injury", "hurt", "wound", "pain", "accident",
        "unconscious", "breathing", "poison", "bite", "sting",
    },
    "emergency_preparedness": {
        "earthquake", "flood", "fire", "smoke", "power", "outage",
        "emergency", "kit", "evacuation", "evacuate", "disaster",
        "prepare", "preparedness", "survival", "blackout", "storm",
        "shelter", "72", "hour",
    },
    "home_safety": {
        "gas", "leak", "water", "shutoff", "electrical", "security",
        "child", "home", "safety", "circuit", "breaker", "lock",
        "fire", "smoke",
    },
    "mental_health": {
        "mental", "health", "crisis", "suicide", "depression",
        "anxiety", "stress", "help", "counseling", "hopeless",
        "sad", "panic", "breathing", "calm", "therapy", "sleep",
        "mood", "self", "harm", "worry", "fear", "trauma",
    },
    "natural_disasters_india": {
        "cyclone", "heat", "wave", "landslide", "thunderstorm",
        "lightning", "flood", "ndrf", "imd", "india", "disaster",
        "storm", "rain", "natural",
    },
}


def _load_index() -> list:
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("docs", [])
    except Exception as e:
        log.warning(f"offline_kit.index_load_failed | reason={e}")
        return []


def is_available() -> bool:
    return INDEX_PATH.exists() and DOCS_PATH.exists()


def list_docs() -> list:
    return [
        {
            "id": d.get("id"),
            "title": d.get("title"),
            "summary": d.get("summary"),
        }
        for d in _load_index()
    ]


def _tokens(query: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z0-9]+", (query or "").lower())
    return [t for t in raw if t not in STOPWORDS and len(t) > 1]


def _is_utility_query(query: str) -> bool:
    q = (query or "").lower().strip()
    return any(re.search(pattern, q) for pattern in UTILITY_QUERY_PATTERNS)


def _doc_domain_matches(doc_id: str, query: str) -> bool:
    q_tokens = set(_tokens(query))

    if not q_tokens:
        return False

    domain_keywords = DOC_DOMAIN_KEYWORDS.get(doc_id)

    if not domain_keywords:
        # If a doc has no explicit domain guard, allow score threshold to decide.
        return True

    return bool(q_tokens & domain_keywords)


def search(query: str, max_results: int = 2) -> list:
    if not query:
        return []

    if _is_utility_query(query):
        log.info(f"offline_kit.skipped | reason=utility_query query={query!r}")
        return []

    words = _tokens(query)

    if not words:
        log.info(f"offline_kit.skipped | reason=no_content_tokens query={query!r}")
        return []

    scored = []

    for doc in _load_index():
        doc_id = doc.get("id", "")

        if not _doc_domain_matches(doc_id, query):
            log.info(
                f"offline_kit.doc_skipped | reason=domain_mismatch "
                f"doc={doc_id} query={query!r}"
            )
            continue

        score = 0
        title = doc.get("title", "").lower()
        summary = doc.get("summary", "").lower()
        keywords = [k.lower() for k in doc.get("keywords", [])]

        for word in words:
            if word in keywords:
                score += 5

            if word in title:
                score += 3

            if word in summary:
                score += 2

            for kw in keywords:
                if word in kw or kw in word:
                    score += 1

        if score >= MIN_DOC_SCORE:
            scored.append((score, doc))
        else:
            log.info(
                f"offline_kit.doc_skipped | reason=low_score "
                f"doc={doc_id} score={score} min={MIN_DOC_SCORE} query={query!r}"
            )

    scored.sort(key=lambda x: x[0], reverse=True)

    results = [doc for _, doc in scored[:max_results]]

    log.info(
        f"offline_kit.search | query={query!r} tokens={words} "
        f"results={len(results)}"
    )

    return results


def _read_doc(file_name: str) -> str | None:
    file_path = DOCS_PATH / file_name

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        log.warning(f"offline_kit.read_failed | file={file_name} reason={e}")
        return None


def _best_section(query: str, content: str, max_chars: int = 300) -> str | None:
    q_tokens = _tokens(query)
    q = " ".join(q_tokens)

    sections = [s.strip() for s in content.split(SECTION_SPLIT) if s.strip()]

    if not sections:
        return content[:max_chars]

    scored = []

    for sec in sections:
        s = sec.lower()
        score = 0

        # First aid terms
        if "bleed" in q and "bleed" in s:
            score += 8

        if "blood" in q and "blood" in s:
            score += 6

        if "wound" in q and "wound" in s:
            score += 5

        if "burn" in q and "burn" in s:
            score += 8

        if "chok" in q and "chok" in s:
            score += 8

        if "fever" in q and "fever" in s:
            score += 8

        if "cpr" in q and "cpr" in s:
            score += 8

        if "fracture" in q and "fracture" in s:
            score += 7

        if "dehydration" in q and "dehydration" in s:
            score += 7

        # Emergency preparedness / disaster terms
        if "fire" in q and "fire" in s:
            score += 8

        if "smoke" in q and "smoke" in s:
            score += 6

        if "evacuat" in q and "evacuat" in s:
            score += 8

        if "earthquake" in q and "earthquake" in s:
            score += 8

        if "flood" in q and "flood" in s:
            score += 8

        if "power" in q and "power" in s:
            score += 5

        if "outage" in q and "outage" in s:
            score += 5

        if "blackout" in q and "blackout" in s:
            score += 6

        if "emergency" in q and "emergency" in s:
            score += 5

        if "gas" in q and "gas" in s:
            score += 6

        if "leak" in q and "leak" in s:
            score += 6

        if "cyclone" in q and "cyclone" in s:
            score += 8

        if "lightning" in q and "lightning" in s:
            score += 8

        if "thunderstorm" in q and "thunderstorm" in s:
            score += 8

        if "landslide" in q and "landslide" in s:
            score += 8

        if "heat" in q and "heat" in s and "wave" in q and "wave" in s:
            score += 8

        # Mental health terms
        if "anxiety" in q and "anxiety" in s:
            score += 8

        if "panic" in q and "panic" in s:
            score += 8

        if "depression" in q and "depression" in s:
            score += 8

        if "suicide" in q and "suicide" in s:
            score += 10

        if "stress" in q and "stress" in s:
            score += 6

        if "breathing" in q and "breathing" in s:
            score += 6

        # Penalize mismatched CPR sections for unrelated first-aid questions.
        if "bleed" in q and (
            "cpr" in s or "compressions" in s or "rescue breaths" in s
        ):
            score -= 6

        # General token overlap
        for token in q_tokens:
            if token in s:
                score += 1

        scored.append((score, sec))

    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best = scored[0]

    if best_score < MIN_SECTION_SCORE:
        log.info(
            f"offline_kit.section_skipped | reason=low_score "
            f"score={best_score} min={MIN_SECTION_SCORE} query={query!r}"
        )
        return None

    log.info(
        f"offline_kit.section_selected | score={best_score} query={query!r}"
    )

    return best[:max_chars]


def search_and_inject(query: str) -> str | None:
    matches = search(query, max_results=1)

    if not matches:
        log.info(f"offline_kit.no_match | query={query!r}")
        return None

    top = matches[0]
    content = _read_doc(top["file"])

    if not content:
        return None

    best = _best_section(query, content, max_chars=300)

    if not best:
        log.info(
            f"offline_kit.no_relevant_section | doc={top.get('id')} "
            f"query={query!r}"
        )
        return None

    context = f"[OFFLINE KIT: {top['title']}]\n{best}"

    log.info(f"offline_kit.injected | doc={top['id']} query={query!r}")

    return context
