import requests
from core.logger import get_logger

log = get_logger("local_llm")

LOCAL_LLM_URL = "http://localhost:8080/v1/chat/completions"
TIMEOUT_SECONDS = 20
MAX_TOKENS = 90
TEMPERATURE = 0.2

SYSTEM_PROMPT = """You are Clarity, an offline safety assistant on a SafeBox device.
Answer the user directly in calm, short, practical language.
Do not describe, summarize, or comment on reference text.
Do not say things like 'the information says', 'the document says', or 'the reference says'.
Use reference text only to answer the user's question.
Keep the answer to 2 to 4 short sentences.
For urgent safety or first-aid questions, give immediate actionable steps first.
"""


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
        "the information provided",
        "the given information",
        "the reference says",
        "the document says",
        "offline kit",
        "using this information",
        "first aid quick reference",
        "rule:",
    ]

    answer_lower = answer.lower()
    return any(marker in answer_lower for marker in bad_markers)


def ask_local_llm(prompt: str, inject_kit: bool = True) -> str | None:
    if not prompt:
        return None

    fast = emergency_fastpath(prompt)
    if fast:
        log.info("local_llm.fastpath_hit")
        return fast

    user_prompt = _build_user_prompt(prompt, inject_kit)

    try:
        log.info("local_llm.sending")
        response = requests.post(
            LOCAL_LLM_URL,
            json={
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
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
        return answer

    except requests.exceptions.Timeout:
        log.warning("local_llm.timeout")
        return None
    except Exception as e:
        log.warning(f"local_llm.error | {e}")
        return None
