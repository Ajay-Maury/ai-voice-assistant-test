from openai import AzureOpenAI
from config.settings import (
    AI_SYSTEM_PROMPT,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_MODEL,
)

azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)
azure_model = AZURE_OPENAI_MODEL


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

        response = azure_client.chat.completions.create(
            model=azure_model,
            messages=messages, # type: ignore
        )
        content = response.choices[0].message.content
        return content.strip() if content is not None else ""
    except Exception as e:
        print("Azure OpenAI error:", e)
        return "Sorry, something went wrong."
