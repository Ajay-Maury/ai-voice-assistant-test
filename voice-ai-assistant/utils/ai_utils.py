from openai import OpenAI
from config.settings import (
    AI_SYSTEM_PROMPT,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)

openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
)
openai_model = OPENAI_MODEL


def get_ai_response(user_input, context=[]):
    try:
        print("User input:", user_input)
        messages = [
            {
                "role": "system",
                "content": AI_SYSTEM_PROMPT,
            }
        ]
        for u, a in context:
            messages.append({"role": "user", "content": u})
            messages.append({"role": "assistant", "content": a})
        messages.append({"role": "user", "content": user_input})

        response = openai_client.chat.completions.create(
            model=openai_model,
            messages=messages, # type: ignore
        )
        content = response.choices[0].message.content
        return content.strip() if content is not None else ""
    except Exception as e:
        print("OpenAI error:", e)
        return "Sorry, something went wrong."
