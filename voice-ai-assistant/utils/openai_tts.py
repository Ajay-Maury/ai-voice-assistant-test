import os
import uuid
import subprocess
import tempfile
import asyncio
from openai import OpenAI, AsyncOpenAI
from config.settings import (
    OPENAI_API_KEY,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    RESPONSE_AUDIO_CHUNK_DIR,
)

def synthesize_openai_tts_to_pcm(text):
    """Non-streaming version of TTS synthesis (kept for compatibility)"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Generate speech using OpenAI TTS with higher quality
        response = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="wav",  # Better quality than MP3
            speed=1.0
        )
        
        # Save the WAV response
        wav_path = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, f"tts_{uuid.uuid4()}.wav")
        with open(wav_path, "wb") as f:
            f.write(response.content)
        
        # Convert WAV to μ-law PCM format (8kHz, 8-bit, mono, μ-law)
        raw_path = wav_path.replace(".wav", ".raw")
        
        try:
            subprocess.run([
                "ffmpeg",
                "-i", wav_path,           # input WAV file
                "-ar", "8000",            # output sample rate (8kHz for Twilio)
                "-ac", "1",               # mono
                "-acodec", "pcm_mulaw",   # explicit μ-law codec
                "-f", "mulaw",            # output format μ-law
                "-y",                     # overwrite output
                raw_path                  # output file
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Read the converted μ-law data
            with open(raw_path, "rb") as f:
                audio_data = f.read()
            
            # Clean up temporary files
            if os.path.exists(wav_path):
                os.remove(wav_path)
            if os.path.exists(raw_path):
                os.remove(raw_path)
                
            return audio_data
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] FFmpeg conversion failed: {e}")
            return None
            
    except Exception as e:
        print(f"[ERROR] OpenAI TTS failed: {e}")
        return None


async def convert_wav_chunk_to_mulaw(wav_chunk):
    """Convert a WAV chunk to μ-law format for streaming"""
    temp_wav_path = None
    temp_raw_path = None
    
    try:
        # Create a temporary directory that won't be automatically deleted
        temp_dir = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Create temporary files with unique names
        unique_id = uuid.uuid4()
        temp_wav_path = os.path.join(temp_dir, f"temp_{unique_id}.wav")
        temp_raw_path = os.path.join(temp_dir, f"temp_{unique_id}.raw")
        
        # Write the WAV data to the temporary file
        with open(temp_wav_path, "wb") as temp_wav_file:
            temp_wav_file.write(wav_chunk)
        
        # Convert to μ-law using ffmpeg
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", temp_wav_path,       # input WAV file
            "-ar", "8000",            # output sample rate (8kHz for Twilio)
            "-ac", "1",               # mono
            "-acodec", "pcm_mulaw",   # explicit μ-law codec
            "-f", "mulaw",            # output format μ-law
            "-y",                     # overwrite output
            temp_raw_path,            # output file
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        
        await process.wait()
        
        # Read the converted μ-law data
        if os.path.exists(temp_raw_path):
            with open(temp_raw_path, "rb") as f:
                audio_data = f.read()
        else:
            print(f"[ERROR] Raw file not created: {temp_raw_path}")
            return None
            
        return audio_data
        
    except Exception as e:
        print(f"[ERROR] WAV chunk conversion failed: {e}")
        return None
        
    finally:
        # Clean up temporary files
        try:
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.remove(temp_wav_path)
            if temp_raw_path and os.path.exists(temp_raw_path):
                os.remove(temp_raw_path)
        except Exception as e:
            print(f"[ERROR] Failed to clean up temp files: {e}")


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
        