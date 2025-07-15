import asyncio
import os
import uuid
import whisper
from openai import AsyncOpenAI, OpenAI
from config.settings import (
    AI_SYSTEM_PROMPT,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_STT_MODEL,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    RESPONSE_AUDIO_CHUNK_DIR,
)

from utils.audio_utils import convert_wav_to_mulaw


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


def detect_audio_language_whisper(audio_file_path: str) -> str:
    model = whisper.load_model("base")
    audio = whisper.load_audio(audio_file_path)
    audio = whisper.pad_or_trim(audio)
    mel = whisper.log_mel_spectrogram(audio).to(model.device)
    _, probs = model.detect_language(mel)
    return max(probs, key=probs.get)      # type: ignore


def transcribe_audio_whisper(filepath, lang="en"):
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        with open(filepath, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model=OPENAI_STT_MODEL, 
                file=audio_file, 
                language=lang
            )
        print(f"whisper stt response---: {result.text}")
        return result.text.strip() if result.text else ""
    except Exception as e:
        print("OpenAI Whisper error:", e)
        return ""


def stream_text_to_mulaw_chunks(text: str) -> bytes:
    """
    Synthesize speech using OpenAI TTS and convert to μ-law format.

    Args:
        text (str): The text to synthesize.

    Returns:
        bytes: μ-law encoded speech audio data.
    """
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        response = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="wav",
            speed=1.0
        )

        temp_wav_path = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, f"tts_{uuid.uuid4()}.wav")

        # Save the WAV data
        with open(temp_wav_path, "wb") as f:
            f.write(response.content)

        return convert_wav_to_mulaw(temp_wav_path)

    except Exception as e:
        print(f"[ERROR] OpenAI TTS synthesis failed: {e}")
        return b""


async def stream_openai_tts(text):
    """Stream TTS audio chunks from OpenAI"""
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        # Create streaming response
        response = await client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="wav",
            speed=1.0
        )
        
        # For streaming, we'll first save the complete response to avoid conversion issues
        temp_wav_path = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, f"full_tts_{uuid.uuid4()}.wav")
        temp_raw_path = temp_wav_path.replace(".wav", ".raw")
        
        # Save the complete WAV file
        with open(temp_wav_path, "wb") as f:
            f.write(response.content)
        
        # Convert the entire file to μ-law
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-i", temp_wav_path,       # input WAV file
                "-ar", "8000",            # output sample rate (8kHz for Twilio)
                "-ac", "1",               # mono
                "-acodec", "pcm_mulaw",   # explicit μ-law codec
                "-af", "highpass=f=200,lowpass=f=3400",  # Apply audio filters to reduce noise
                "-f", "mulaw",            # output format μ-law
                "-y",                     # overwrite output
                temp_raw_path,            # output file
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            await process.wait()
            
            # Read the converted μ-law data
            with open(temp_raw_path, "rb") as f:
                audio_data = f.read()
            
            # Clean up temporary files
            if os.path.exists(temp_wav_path):
                os.remove(temp_wav_path)
            if os.path.exists(temp_raw_path):
                os.remove(temp_raw_path)
            
            # Return the response as an async generator
            async def audio_chunk_generator():
                # Process the audio in smaller chunks for streaming
                chunk_size = 1024  # Smaller, more consistent chunks (128ms at 8kHz)
                for i in range(0, len(audio_data), chunk_size):
                    yield audio_data[i:i+chunk_size]
                    # Smaller delay for smoother streaming
                    await asyncio.sleep(0.005)
            
            return audio_chunk_generator()
            
        except Exception as e:
            print(f"[ERROR] FFmpeg conversion failed: {e}")
            return None
            
    except Exception as e:
        print(f"[ERROR] OpenAI TTS streaming failed: {e}")
        return None
        