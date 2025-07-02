import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

azure_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=str(os.getenv("AZURE_OPENAI_ENDPOINT")),
)
azure_model = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-35-turbo")


def get_ai_response(user_input, context=[]):
    try:
        print("User input:", user_input)
        print("Context:", context)
        messages = [
            {
                "role": "system",
                "content": "You are a friendly, conversational human assistant. Respond naturally and warmly, as if you are speaking to a friend. Keep responses concise and conversational, suitable for voice interaction. Limit responses to 1-2 sentences.",
            }
        ]
        for u, a in context:
            messages.append({"role": "user", "content": u})
            messages.append({"role": "assistant", "content": a})
        messages.append({"role": "user", "content": user_input})

        response = azure_client.chat.completions.create(
            model=azure_model,
            messages=messages,
        )
        content = response.choices[0].message.content
        return content.strip() if content is not None else ""
    except Exception as e:
        print("Azure OpenAI error:", e)
        return "Sorry, something went wrong."
