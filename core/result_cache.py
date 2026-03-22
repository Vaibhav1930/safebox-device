"""
core/result_cache.py
Local Result Cache — Phase 1.5 alignment (optional)

Caches recent cloud LLM responses locally so repeated identical or
near-identical questions don't hit the cloud API unnecessarily.

Cache is stored as a JSON file on the SSD vault. Each entry is keyed
by a normalized hash of the user query. Cache entries expire after
CACHE_TTL_SECONDS.

Usage:
    from core.result_cache import get_cached, store_result

    cached = get_cached(user_text)
    if cached:
        return cached

    result = ask_llm(user_text, ...)
    store_result(user_text, result)
    return result
"""

import os
import json
import time
import hashlib
from pathlib import Path
from core.logger import get_logger

log = get_logger("result_cache")

CACHE_TTL_SECONDS = 300          # 5 minutes
MAX_CACHE_ENTRIES = 50           # max entries before pruning oldest
VAULT_ROOT        = os.environ.get("SAFEBOX_VAULT_ROOT", "/mnt/ssd/safebox-device/vault")
CACHE_PATH        = Path(VAULT_ROOT) / "result_cache.json"


def _normalize(text: str) -> str:
    """Normalize query text for consistent cache key generation."""
    return text.lower().strip()


def _cache_key(text: str) -> str:
    """Generate a short hash key from normalized query text."""
    return hashlib.sha256(_normalize(text).encode()).hexdigest()[:16]


def _load() -> dict:
    try:
        if CACHE_PATH.exists():
            with open(CACHE_PATH) as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"result_cache.load_failed | {e}")
    return {}


def _save(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log.warning(f"result_cache.save_failed | {e}")


def _prune(cache: dict) -> dict:
    """Remove expired entries. If still over limit, remove oldest."""
    now = time.time()
    # Remove expired
    cache = {
        k: v for k, v in cache.items()
        if now - v.get("cached_at", 0) < CACHE_TTL_SECONDS
    }
    # If still over limit, remove oldest
    if len(cache) > MAX_CACHE_ENTRIES:
        sorted_keys = sorted(cache, key=lambda k: cache[k].get("cached_at", 0))
        for k in sorted_keys[:len(cache) - MAX_CACHE_ENTRIES]:
            del cache[k]
    return cache


def get_cached(user_text: str) -> dict | None:
    """
    Return a cached result for this query if one exists and hasn't expired.

    Returns:
        dict with 'response' and 'request_id' keys, or None if no valid cache hit.
    """
    if not user_text:
        return None

    cache = _load()
    key   = _cache_key(user_text)
    entry = cache.get(key)

    if not entry:
        return None

    age = time.time() - entry.get("cached_at", 0)
    if age > CACHE_TTL_SECONDS:
        log.info(f"result_cache.expired | key={key} age={int(age)}s")
        return None

    log.info(f"result_cache.hit | key={key} age={int(age)}s query={user_text[:40]!r}")
    return entry.get("result")


def store_result(user_text: str, result: dict):
    """
    Store a cloud LLM result in the local cache.

    Args:
        user_text: The original user query.
        result:    The result dict from ask_llm() — must have 'response' key.
    """
    if not user_text or not result or not result.get("response"):
        return

    cache = _load()
    cache = _prune(cache)

    key = _cache_key(user_text)
    cache[key] = {
        "query":     _normalize(user_text),
        "result":    result,
        "cached_at": time.time(),
    }

    _save(cache)
    log.info(f"result_cache.stored | key={key} query={user_text[:40]!r}")


def clear_cache():
    """Clear all cached results."""
    try:
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
        log.info("result_cache.cleared")
    except Exception as e:
        log.warning(f"result_cache.clear_failed | {e}")


def cache_stats() -> dict:
    """Return current cache statistics."""
    cache = _load()
    now   = time.time()
    valid = sum(
        1 for v in cache.values()
        if now - v.get("cached_at", 0) < CACHE_TTL_SECONDS
    )
    return {
        "total_entries": len(cache),
        "valid_entries": valid,
        "expired_entries": len(cache) - valid,
        "cache_path": str(CACHE_PATH),
        "ttl_seconds": CACHE_TTL_SECONDS,
    }
