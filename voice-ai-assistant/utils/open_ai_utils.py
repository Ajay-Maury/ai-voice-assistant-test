import asyncio
import os
import time
import uuid
from groq import Groq
import whisper
from openai import AsyncOpenAI, OpenAI
from config.settings import (
    GROQ_API_KEY,
    GROQ_CHAT_TEMPERATURE,
    GROQ_STT_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    WHISPER_STT_OFFLINE_MODEL,  
)

from utils.langchain_agent import LangChainAIAgent


openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
)
openai_model = OPENAI_MODEL
groq_client = Groq(api_key=GROQ_API_KEY)


# Load once and reuse (recommended for performance)
whisper_model = whisper.load_model(WHISPER_STT_OFFLINE_MODEL)  # Options: tiny, base, small, medium, large

langchain_agent = LangChainAIAgent()

async def get_ai_response(user_input, context=None, call_sid="default"):
    try:
        print("User input:", user_input)
        
        # Convert the Redis context format to the expected format
        redis_context = context if context else []
        
        # Use the langchain agent to process the query with Redis context
        response = await langchain_agent.process_query(user_input, call_sid, redis_context)
        
        return response.strip() if response else ""
    except Exception as e:
        print("LangChain agent error:", e)
        return "Sorry, something went wrong."




def transcribe_audio_whisper_groq(filepath, lang="hi"):
    try:
        start_time = time.time()
        print(f"Transcribing {filepath} with groq in {lang} language...")

        with open(filepath, "rb") as audio_file:
            transcription = groq_client.audio.translations.create(
                file=(filepath, audio_file.read()),
                model=GROQ_STT_MODEL,
                prompt="We are trying to talk to people who speaks hindi-english mix language.",
                temperature=GROQ_CHAT_TEMPERATURE
            )
        endtime = time.time()

        print(f"Groq Whisper v3-turbo response time : {endtime - start_time:.2f}")
        print(f"Groq Whisper v3-turbo response: {transcription.text}")
        return transcription.text.strip() if hasattr(transcription, 'text') else ""
    except Exception as e:
        print("Groq Whisper v3-turbo error:", e)
        return ""

