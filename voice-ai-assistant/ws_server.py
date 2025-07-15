import asyncio
import websockets
import json
import base64
import os
import random

# Utility functions for audio handling, transcription, AI interaction, TTS, and Redis context
from utils.audio_utils import is_silent_mulaw_audio, convert_mulaw_to_wav
from utils.utils import get_engagement_response
from utils.openai_tts import stream_openai_tts
from utils.redis_utils import get_context, store_context
from utils.open_ai_utils import get_ai_response, transcribe_audio_whisper

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


# Stream TTS audio directly from OpenAI to client via WebSocket
async def stream_tts_real_time(websocket, stream_sid, text, call_sid, stop_event):
    print(f"[TTS-{call_sid}]: Starting real-time TTS streaming")
    
    # Get streaming TTS generator
    audio_chunk_generator = await stream_openai_tts(text)
    if not audio_chunk_generator:
        print(f"[TTS-{call_sid}]: Failed to create TTS stream")
        return
    
    # Process each audio chunk as it becomes available
    try:
        async for mulaw_chunk in audio_chunk_generator:
            if stop_event.is_set():
                print(f"[TTS-{call_sid}]: Playback interrupted by user")
                break
            
            # Send the chunk in smaller pieces for smooth playback
            chunk_size = AUDIO_CHUNK_SIZE
            for i in range(0, len(mulaw_chunk), chunk_size):
                if stop_event.is_set():
                    break
                
                sub_chunk = mulaw_chunk[i : i + chunk_size]
                try:
                    await websocket.send(
                        json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(sub_chunk).decode()},
                        })
                    )
                except websockets.exceptions.ConnectionClosed: # type: ignore /  WebSocket closed unexpectedly
                    print(f"[TTS-{call_sid}]: WebSocket closed during playback")
                    return
                
                await asyncio.sleep(0.01)  # Faster playback rate for smoother audio
    
    except Exception as e:
        print(f"[TTS-{call_sid}]: Streaming error: {e}")
    
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
async def handler(websocket):
    print("[+] WebSocket connected")

    # Buffers and control variables
    buffer = b""  # For saving to disk
    raw_buffer = b""  # For detecting silence/barge-in
    call_sid = ""
    stream_sid = None
    tts_task = None
    tts_stop_event = asyncio.Event()
    handler_stop_event = asyncio.Event()
    last_audio_time = asyncio.get_event_loop().time()
    silence_task = None
    backchannel_task = None
    last_backchannel_time = 0
    speech_start_time = 0
    tts_type = None


    async def monitor_user_engagement():
        print(f"[Engagement-{call_sid}]: Starting user engagement monitor")
        nonlocal last_backchannel_time, speech_start_time, tts_task, tts_type

        silent_since = None

        while not handler_stop_event.is_set():
            await asyncio.sleep(1.0)
            now = asyncio.get_event_loop().time()

            user_is_talking = len(raw_buffer) > MIN_AUDIO_BYTES
            tts_active = tts_task and not tts_task.done()

            if user_is_talking:
                silent_since = None

                if not tts_active and (now - last_backchannel_time >= 1.5):
                    if speech_start_time > 0 and (now - speech_start_time >= 1.5):
                        text = get_engagement_response("ENGAGED", "en")
                        last_backchannel_time = now

                        print(f"[Engagement-{call_sid}]: Sending text '{text}'")
                        try:
                            tts_stop_event.clear()
                            tts_type = "engagement_reply"
                            tts_task = asyncio.create_task(
                                stream_tts_real_time(websocket, stream_sid, text, call_sid, tts_stop_event)
                            )
                        except Exception as e:
                            print(f"[Engagement-{call_sid}]: Error sending text: {e}")

            else:
                if silent_since is None:
                    silent_since = now
                elif now - silent_since >= 5.0 and (not tts_active):
                    last_backchannel_time = now
                    text = get_engagement_response("DISENGAGED", "en")
                    print(f"[Engagement-{call_sid}]: User silent for 10+ seconds, sending check-in:- '{text}'")

                    try:
                        tts_stop_event.clear()
                        tts_type = "engagement_reply"
                        tts_task = asyncio.create_task(
                            stream_tts_real_time(websocket, stream_sid, text, call_sid, tts_stop_event)
                        )
                    except Exception as e:
                        print(f"[Engagement-{call_sid}]: Error sending check-in: {e}")


    # Background task to detect silence or barge-in
    async def detect_silence():
        print(f"[Silence-{call_sid}]: Starting silence detection")
        nonlocal buffer, last_audio_time, tts_task, raw_buffer, speech_start_time, tts_type

        while not handler_stop_event.is_set():
            await asyncio.sleep(0.25)
            now = asyncio.get_event_loop().time()
            elapsed = now - last_audio_time

            # Barge-in detection: if user speaks while TTS is playing
            if len(raw_buffer) > MIN_AUDIO_BYTES and tts_task and not tts_task.done() and tts_type == "ai_reply":  # Only interrupt AI replies, not backchannel
                print(f"[Barge-in-{call_sid}]: User interrupted TTS playback")
                tts_stop_event.set()
                await wait_for_tts_cleanup(tts_task)

                # Inform client that playback was interrupted
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
                    audio_file = convert_mulaw_to_wav(call_sid, buffer)
                    buffer = b""
                    raw_buffer = b""
                    speech_duration = asyncio.get_event_loop().time() - speech_start_time
                    speech_start_time = 0

                    result = transcribe_audio_whisper(audio_file)
                    text = result if isinstance(result, str) else result.get("text")

                    if not text:
                        continue

                    print(f"[User-{call_sid}]: {text}")

                    if tts_task and not tts_task.done() and tts_type == "engagement_reply":
                        print(f"[Silence-{call_sid}]: Stopping engagement_reply previous TTS task-------")
                        
                        await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
                        await websocket.send(
                                json.dumps({
                                    "event": "mark",
                                    "streamSid": stream_sid,
                                    "mark": {"name": "engagement_reply_tts_interrupted"},
                                })
                            )

                    # Get conversation context and AI response
                    context = get_context(call_sid)
                    ai_reply = get_ai_response(text, context)
                    print("[AI Reply]:", ai_reply)
                    store_context(call_sid, text, ai_reply)

                    # Use streaming TTS for faster response
                    tts_stop_event.clear()
                    tts_type = "ai_reply"
                    tts_task = asyncio.create_task(
                        stream_tts_real_time(
                            websocket,
                            stream_sid,
                            ai_reply,
                            call_sid,
                            tts_stop_event,
                        )
                    )
                except Exception as e:
                    print(f"[Silence-{call_sid}]: Error during processing: {e}")

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
                backchannel_task = asyncio.create_task(monitor_user_engagement())

            elif event == "media":
                # Incoming audio chunk from client
                if not call_sid:
                    continue
                audio_b64 = data["media"]["payload"]
                new_chunk = base64.b64decode(audio_b64)
                buffer += new_chunk

                # Skip silent chunks
                if is_silent_mulaw_audio(new_chunk):
                    continue

                # Append to raw buffer and reset silence timer
                raw_buffer += new_chunk
                last_audio_time = asyncio.get_event_loop().time()
                if speech_start_time == 0:
                    speech_start_time = last_audio_time

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

        # Stop backchannel responder task
        if backchannel_task:
            backchannel_task.cancel()
            try:
                await backchannel_task
            except asyncio.CancelledError:
                print(f"[Cleanup-{call_sid}]: Backchannel task cancelled")

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
