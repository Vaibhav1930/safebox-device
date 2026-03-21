import json
import os
from pathlib import Path
from core.logger import get_logger

log = get_logger("offline_kit")

KIT_ROOT = Path(os.environ.get("SAFEBOX_VAULT_ROOT", "/mnt/ssd/safebox-device/vault")).parent / "offline_kit"
INDEX_PATH = KIT_ROOT / "index.json"
DOCS_PATH = KIT_ROOT / "docs"

SECTION_SPLIT = "\n\n"


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


def search(query: str, max_results: int = 2) -> list:
    if not query:
        return []

    q = query.lower().strip()
    words = q.split()
    scored = []

    for doc in _load_index():
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

        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [doc for _, doc in scored[:max_results]]
    log.info(f"offline_kit.search | query={query!r} results={len(results)}")
    return results


def _read_doc(file_name: str) -> str | None:
    file_path = DOCS_PATH / file_name
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        log.warning(f"offline_kit.read_failed | file={file_name} reason={e}")
        return None


def _best_section(query: str, content: str, max_chars: int = 450) -> str:
    q = (query or "").lower()
    sections = [s.strip() for s in content.split(SECTION_SPLIT) if s.strip()]
    if not sections:
        return content[:max_chars]

    scored = []
    for sec in sections:
        s = sec.lower()
        score = 0

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

        # Penalize mismatched CPR sections for unrelated questions
        if "bleed" in q and ("cpr" in s or "compressions" in s or "rescue breaths" in s):
            score -= 6

        # General token overlap
        for token in q.split():
            if token in s:
                score += 1

        scored.append((score, sec))

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
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

    best = _best_section(query, content, max_chars=450)
    context = f"[OFFLINE KIT: {top['title']}]\n{best}"
    log.info(f"offline_kit.injected | doc={top['id']} query={query!r}")
    return context
