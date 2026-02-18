import requests

LOCAL_LLM_URL = "http://localhost:8081/v1/chat/completions"
TIMEOUT_SECONDS = 60


def ask_local_llm(prompt: str):
    if not prompt:
        return None

    try:
        print("[LOCAL] Sending to TinyLlama...")

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
            print("[LOCAL LLM ERROR] HTTP", response.status_code)
            return None

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        if not content:
            return None

        print("[LOCAL] Response received")
        return content.strip()

    except requests.exceptions.Timeout:
        print("[LOCAL LLM ERROR] Timeout")
        return None

    except Exception as e:
        print("[LOCAL LLM ERROR]", e)
        return None
