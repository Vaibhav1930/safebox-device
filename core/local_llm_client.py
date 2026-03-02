import requests
from core.logger import get_logger

log = get_logger("local_llm")

LOCAL_LLM_URL = "http://localhost:8080/v1/chat/completions"
TIMEOUT_SECONDS = 60


def ask_local_llm(prompt: str):
    if not prompt:
        return None

    try:
        log.info("local_llm.sending")

        response = requests.post(
            LOCAL_LLM_URL,
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a concise offline assistant. Answer briefly."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 128,
                "temperature": 0.6
            },
            timeout=TIMEOUT_SECONDS
        )

        if response.status_code != 200:
            log.warning(f"local_llm.error http={response.status_code}")
            return None

        data = response.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content")

        if not content:
            log.warning("local_llm.empty_response")
            return None

        log.info("local_llm.response_received")
        return content.strip()

    except requests.exceptions.Timeout:
        log.warning("local_llm.timeout")
        return None

    except Exception as e:
        log.warning(f"local_llm.error {e}")
        return None
