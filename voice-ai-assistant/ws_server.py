import asyncio
import websockets
import json
import base64
import os

# Utility functions for audio handling, transcription, AI interaction, TTS, and Redis context
from utils.audio_utils import (
    save_audio_chunk,
    silent_detected,
    transcribe_audio_azure,
    transcribe_audio_whisper
)
from utils.ai_utils import get_ai_response
from utils.azure_tts import synthesize_azure_tts_to_pcm
from utils.redis_utils import get_context, store_context

# App configuration
from config.settings import (
    AUDIO_BUFFER_SILENCE,
    AUDIO_CHUNK_DIR,
    AUDIO_CHUNK_SIZE,
    MIN_AUDIO_BYTES,
)


# Send TTS audio to client via WebSocket in small chunks (simulates streaming)
async def stream_tts_audio(websocket, stream_sid, audio_bytes, call_sid, stop_event):
    chunk_size = AUDIO_CHUNK_SIZE
    for i in range(0, len(audio_bytes), chunk_size):
        if stop_event.is_set():
            print(f"[TTS-{call_sid}]: Playback interrupted by user")
            break

        chunk = audio_bytes[i : i + chunk_size]
        try:
            await websocket.send(
                json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode()},
                })
            )
        except websockets.exceptions.ConnectionClosed:  # type: ignore /  WebSocket closed unexpectedly
            print(f"[TTS-{call_sid}]: WebSocket closed during playback")
            break

        await asyncio.sleep(0.02)  # Simulate real-time streaming pace

    # Signal to the client that the TTS playback is complete
    if not stop_event.is_set():
        await websocket.send(
            json.dumps({
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": "tts_complete"},
            })
        )


# Ensure TTS task finishes gracefully
async def wait_for_tts_cleanup(task):
    try:
        await asyncio.shield(task)
    except Exception as e:
        print(f"[TTS Cleanup Error]: {e}")


# Main WebSocket handler for each client connection
async def handler(websocket, path):
    print("[+] WebSocket connected")

    # Buffers and control variables
    buffer = b""  # For saving to disk
    raw_buffer = b""  # For detecting silence/barge-in
    call_sid = None
    stream_sid = None
    tts_task = None
    tts_stop_event = asyncio.Event()
    handler_stop_event = asyncio.Event()
    last_audio_time = asyncio.get_event_loop().time()
    silence_task = None

    # Background task to detect silence or barge-in
    async def detect_silence():
        print(f"[Silence-{call_sid}]: Starting silence detection")
        nonlocal buffer, last_audio_time, tts_task, raw_buffer

        while not handler_stop_event.is_set():
            await asyncio.sleep(0.25)
            now = asyncio.get_event_loop().time()
            elapsed = now - last_audio_time

            # Barge-in detection: if user speaks while TTS is playing
            if len(raw_buffer) > MIN_AUDIO_BYTES and tts_task and not tts_task.done():
                print(f"[Barge-in-{call_sid}]: User interrupted TTS playback")
                tts_stop_event.set()
                await wait_for_tts_cleanup(tts_task)

                # Inform client that playback was interrupted
                if websocket.open:
                    await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
                    await websocket.send(
                        json.dumps({
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": "tts_interrupted"},
                        })
                    )

            # Silence timeout detection: user stopped speaking
            if len(raw_buffer) > MIN_AUDIO_BYTES and elapsed >= AUDIO_BUFFER_SILENCE:
                print(f"[Silence-{call_sid}]: Silence detected {elapsed}, processing audio")

                try:
                    # Save audio and transcribe
                    audio_file = save_audio_chunk(call_sid, buffer)
                    buffer = b""
                    raw_buffer = b""

                    # Transcribe using Whisper (or switch to Azure if needed)
                    # text = transcribe_audio_azure(audio_file)
                    text = transcribe_audio_whisper(audio_file)

                    if not text:
                        continue

                    print(f"[User-{call_sid}]: {text}")

                    # Get conversation context and AI response
                    context = get_context(call_sid)
                    ai_reply = get_ai_response(text, context)
                    print("[AI Reply]:", ai_reply)
                    store_context(call_sid, text, ai_reply)

                    # Convert AI response to audio via Azure TTS
                    tts_audio = synthesize_azure_tts_to_pcm(ai_reply)

                    # Stream TTS audio back to the client
                    if tts_audio:
                        tts_stop_event.clear()
                        tts_task = asyncio.create_task(
                            stream_tts_audio(
                                websocket,
                                stream_sid,
                                tts_audio,
                                call_sid,
                                tts_stop_event,
                            )
                        )
                except Exception as e:
                    print(f"[Silence-{call_sid}]: Error during processing: {e}")

    # Handle incoming WebSocket messages
    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                # New stream started
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                print(f"[+] Stream start – callSid={call_sid}, streamSid={stream_sid}")
                silence_task = asyncio.create_task(detect_silence())

            elif event == "media":
                # Incoming audio chunk from client
                if not call_sid:
                    continue
                audio_b64 = data["media"]["payload"]
                new_chunk = base64.b64decode(audio_b64)
                buffer += new_chunk

                # Skip silent chunks
                if silent_detected(new_chunk):
                    continue

                # Append to raw buffer and reset silence timer
                raw_buffer += new_chunk
                last_audio_time = asyncio.get_event_loop().time()

            elif event == "stop":
                # Client ended the stream
                print(f"[+] Stream stopped for callSid={call_sid}")
                handler_stop_event.set()
                break

    except Exception as e:
        print(f"[Handler-{call_sid}]: WebSocket error: {e}")

    finally:
        # Cleanup after WebSocket disconnect or error
        print(f"[Cleanup-{call_sid}]: Cleaning up")
        handler_stop_event.set()

        # Stop and clean up TTS task
        if tts_task and not tts_task.done():
            tts_stop_event.set()
            try:
                await wait_for_tts_cleanup(tts_task)
            except Exception as e:
                print(f"[Cleanup-{call_sid}]: TTS task error: {e}")

        # Stop silence detection task
        if silence_task:
            silence_task.cancel()
            try:
                await silence_task
            except asyncio.CancelledError:
                print(f"[Cleanup-{call_sid}]: Silence task cancelled")

        # Remove temporary audio files for this call
        for filename in os.listdir(AUDIO_CHUNK_DIR):
            if filename.startswith(f"{call_sid}_"):
                file_path = os.path.join(AUDIO_CHUNK_DIR, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except Exception as e:
                    print(f"[Cleanup-{call_sid}]: File removal error: {e}")

        # Notify client and close WebSocket
        try:
            if websocket.open:
                await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
                await websocket.close()
        except Exception as e:
            print(f"[Cleanup-{call_sid}]: WebSocket close error: {e}")


# Entry point: starts the WebSocket server
async def main():
    print("WebSocket server running on port 8765...")
    async with websockets.serve(handler, "0.0.0.0", 8765):  #  type: ignore  / # Accept connections from any IP
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
