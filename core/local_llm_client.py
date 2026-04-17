import os
import requests
from core.logger import get_logger

log = get_logger("local_llm")

LOCAL_LLM_URL = "http://localhost:8080/v1/chat/completions"
TIMEOUT_SECONDS = 40
MAX_TOKENS = 90
TEMPERATURE = 0.2

_FALLBACK_SYSTEM_PROMPT = (
    "You are a home voice assistant on a SafeBox device.\n"
    "Answer the user directly in calm, short, practical language.\n"
    "Do not say things like 'the information says' or 'the document says'.\n"
    "Use reference text only to answer the user's question.\n"
    "Keep the answer to 2 to 4 short sentences.\n"
    "For urgent safety or first-aid questions, give immediate actionable steps first.\n"
)


def _load_runtime_config() -> tuple[dict, dict]:
    """Load persona and behavior dicts from config_sync. Returns (persona, behavior)."""
    try:
        from core.config_sync import ConfigSyncManager
        mgr = ConfigSyncManager(device_id=os.environ.get("DEVICE_NAME", "safebox-001"))
        return mgr.get_persona(), mgr.get_behavior()
    except Exception as e:
        log.warning(f"local_llm.config_load_failed | {e}")
        return {}, {}


def _build_system_prompt(persona: dict, behavior: dict) -> str:
    """Build a runtime-config-driven system prompt."""
    assistant_name = persona.get("assistant_name") or "the home assistant"
    verbosity = persona.get("flags", {}).get("verbosity", "concise")
    length_instruction = (
        "Keep answers to 1 to 2 short sentences."
        if verbosity == "concise"
        else "Keep answers to 2 to 4 sentences."
    )
    return (
        f"You are {assistant_name}, a home voice assistant running on a SafeBox device.\n"
        f"Answer the user directly in calm, short, practical language.\n"
        f"Do not say things like 'the information says', 'the document says', or 'the reference says'.\n"
        f"Use reference text only to answer the user's question.\n"
        f"{length_instruction}\n"
        f"For urgent safety or first-aid questions, give immediate actionable steps first.\n"
    )


def _get_survival_disclosure(behavior: dict) -> str:
    return behavior.get("survival_mode_disclosure", "").strip()


def emergency_fastpath(text: str):
    t = (text or "").strip().lower()
    if not t:
        return None
    if any(term in t for term in ["bleeding", "bleed", "blood", "cut", "wound", "injury"]):
        return (
            "Apply firm pressure to the wound with a clean cloth right away. "
            "Raise the injured area if possible. "
            "If bleeding is heavy, spurting, or does not stop, call 112 immediately."
        )
    if any(term in t for term in ["choking", "can't breathe", "cannot breathe", "something stuck"]):
        return (
            "If the person cannot breathe or speak, give 5 back blows and 5 abdominal thrusts. "
            "Repeat until the object comes out or help arrives. "
            "Call 112 immediately if the person becomes unresponsive."
        )
    if any(term in t for term in ["burn", "burned", "burnt"]):
        return (
            "Cool the burn under running water for 10 to 20 minutes. "
            "Do not use ice and do not pop blisters. "
            "Cover it with a clean non-stick dressing and get medical help for large burns."
        )
    return None


def _build_user_prompt(prompt: str, inject_kit: bool) -> str:
    user_prompt = f"Question: {prompt}"
    if not inject_kit:
        return user_prompt
    try:
        from core.offline_kit import search_and_inject
        kit_context = search_and_inject(prompt)
        if kit_context:
            log.info("local_llm.kit_injected")
            return (
                f"Reference:\n{kit_context}\n\n"
                f"Question: {prompt}\n\n"
                "Answer directly."
            )
    except Exception as e:
        log.warning(f"local_llm.kit_injection_failed | {e}")
    return user_prompt


def _is_bad_answer(answer: str) -> bool:
    if not answer:
        return True
    bad_markers = [
        "the information provided", "the given information", "the reference says",
        "the document says", "offline kit", "using this information",
        "first aid quick reference", "rule:",
    ]
    answer_lower = answer.lower()
    return any(marker in answer_lower for marker in bad_markers)


def ask_local_llm(
    prompt: str,
    inject_kit: bool = True,
    persona: dict | None = None,
    behavior: dict | None = None,
    survival_fallback: bool = False,
) -> str | None:
    """
    Ask the local LLM.

    Args:
        prompt:            User utterance.
        inject_kit:        Whether to inject the offline reference kit.
        persona:           Runtime persona dict. If None, loaded automatically.
        behavior:          Runtime behavior dict. If None, loaded automatically.
        survival_fallback: When True, prepend the survival_mode_disclosure so
                           the user knows they are in offline mode.
    """
    if not prompt:
        return None

    # Load config once if not passed in
    if persona is None or behavior is None:
        _persona, _behavior = _load_runtime_config()
        persona = persona or _persona
        behavior = behavior or _behavior

    fast = emergency_fastpath(prompt)
    if fast:
        log.info("local_llm.fastpath_hit")
        if survival_fallback:
            disclosure = _get_survival_disclosure(behavior)
            return f"{disclosure} {fast}" if disclosure else fast
        return fast

    user_prompt = _build_user_prompt(prompt, inject_kit)
    system_prompt = _build_system_prompt(persona, behavior)

    try:
        log.info("local_llm.sending")
        response = requests.post(
            LOCAL_LLM_URL,
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            },
            timeout=TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            log.warning(f"local_llm.http_error | status={response.status_code}")
            return None

        content = (
            response.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

        if not content:
            log.warning("local_llm.empty_response")
            return None

        answer = content.strip()

        if _is_bad_answer(answer):
            log.warning("local_llm.bad_meta_answer")
            return None

        log.info("local_llm.response_received")

        if survival_fallback:
            disclosure = _get_survival_disclosure(behavior)
            return f"{disclosure} {answer}" if disclosure else answer

        return answer

    except requests.exceptions.Timeout:
        log.warning("local_llm.timeout")
        return None
    except Exception as e:
        log.warning(f"local_llm.error | {e}")
        return None
