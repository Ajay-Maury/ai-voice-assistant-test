import asyncio
import websockets
import json
import base64
import os
import numpy as np
from utils.audio_utils import save_audio_chunk, transcribe_audio, transcribe_audio_azure
from utils.ai_utils import get_ai_response
from utils.azure_tts import synthesize_azure_tts_to_pcm
from utils.redis_utils import get_context, store_context

AUDIO_DIR = "audio_chunks"

# Silence detector
def silent_detected(pcm_data, threshold=150.0):
    if len(pcm_data) < 2:
        return True  # Not enough data to analyze

    pcm_array = np.frombuffer(pcm_data, dtype=np.int16)

    if pcm_array.size == 0:
        print("[Silence Check]: Empty PCM data")
        return True  # Definitely silent

    rms = np.sqrt(np.mean(np.square(pcm_array))) or 0.0

    if rms <= 0.0:
        print("[Silence Check]: Invalid RMS value:-", rms)
        return True

    if not rms < threshold:
        print(f"RMS typee: {type(rms)}, rms value: {rms}")
        print(f"[Silence Check]: RMS={rms:.2f}")

    return rms < threshold


# TTS Streaming
async def stream_tts_audio(websocket, stream_sid, audio_bytes, call_sid, stop_event):
    chunk_size = 160  # 20ms of 8kHz mu-law audio
    for i in range(0, len(audio_bytes), chunk_size):
        if stop_event.is_set():
            print(f"[TTS-{call_sid}]: Playback interrupted by user")
            break
        chunk = audio_bytes[i : i + chunk_size]
        await websocket.send(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode()},
                }
            )
        )
        await asyncio.sleep(0.02)

    if not stop_event.is_set():
        await websocket.send(
            json.dumps(
                {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "tts_complete"},
                }
            )
        )


async def wait_for_tts_cleanup(task):
    try:
        print("[TTS Cleanup]: Waiting for TTS task to finish")
        await asyncio.shield(task)
    except Exception as e:
        print(f"[TTS Cleanup Error]: {e}")


# WebSocket handler
async def handler(websocket, path):
    print("[+] WebSocket connected")
    buffer = b""
    call_sid = None
    stream_sid = None
    tts_task = None
    tts_stop_event = asyncio.Event()
    handler_stop_event = asyncio.Event()
    last_audio_time = asyncio.get_event_loop().time()
    silence_task = None

    async def detect_silence():
        print(f"[Silence-{call_sid}]: Starting silence detection")
        nonlocal buffer, last_audio_time, tts_task

        while not handler_stop_event.is_set():
            await asyncio.sleep(0.25)  # Check every 250ms
            if not buffer or len(buffer) <= 0:
                print(f"[Silence-{call_sid}]: No audio buffer to process")
                continue
            now = asyncio.get_event_loop().time()
            elapsed = now - last_audio_time
            print(
                f"[Silence-{call_sid}]: buffer size = {len(buffer)}, elapsed = {elapsed:.2f}s"
            )

            if buffer and tts_task and not tts_task.done():
                print(f"[Barge-In-{call_sid}]: Interrupting ongoing TTS")
                tts_stop_event.set()
                await wait_for_tts_cleanup(tts_task)

                if websocket.open:
                    await websocket.send(
                        json.dumps({"event": "clear", "streamSid": stream_sid})
                    )
                    await websocket.send(
                        json.dumps(
                            {
                                "event": "mark",
                                "streamSid": stream_sid,
                                "mark": {"name": "tts_interrupted"},
                            }
                        )
                    )

            if buffer and elapsed >= 2:
                print(
                    f"[Silence-{call_sid}]: 2s of silence detected, processing audio buffer"
                )
                try:
                    audio_file = save_audio_chunk(call_sid, buffer)
                    buffer = b""
                    text = transcribe_audio(audio_file)
                    # text = transcribe_audio_azure(audio_file)

                    if not text:
                        print(f"[Silence-{call_sid}]: No transcription result")
                        continue

                    print(f"------[User-{call_sid}]-----: {text}")

                    context = get_context(call_sid)
                    ai_reply = get_ai_response(text, context)
                    print("User input:", text)
                    print("Context:", context)
                    print("---AI Reply-----", ai_reply)

                    store_context(call_sid, text, ai_reply)

                    tts_audio = synthesize_azure_tts_to_pcm(ai_reply)
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

    async for message in websocket:
        try:
            data = json.loads(message)
            event = data.get("event")
            # print(f"[Event-{event}]: Received")

            if event == "start":
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                print(f"[+] Stream start – callSid={call_sid}, streamSid={stream_sid}")
                silence_task = asyncio.create_task(detect_silence())

            elif event == "media":
                if not call_sid:
                    print("[Media]: Ignoring because call_sid not yet set")
                    continue

                audio_b64 = data["media"]["payload"]
                new_chunk = base64.b64decode(audio_b64)

                if silent_detected(new_chunk):
                    # print(f"\n[Media-{call_sid}]: Chunk is silent – skipping\n")
                    continue

                buffer += new_chunk
                print(f"\n[Media-{call_sid}]: Chunk is not silent – adding to buffer")
                last_audio_time = asyncio.get_event_loop().time()
                # print(f"[Media-{call_sid}]: Received audio chunk, buffer={len(buffer)} bytes")
                print(
                    f"[Media-{call_sid}]: Updated last_audio_time to {last_audio_time}\n"
                )

            elif event == "stop":
                print(f"[+] Stream stopped for callSid={call_sid}")
                handler_stop_event.set()

                if tts_task and not tts_task.done():
                    tts_stop_event.set()
                    await wait_for_tts_cleanup(tts_task)

                if silence_task:
                    silence_task.cancel()
                    print(f"[Silence-{call_sid}]: Silence detector cancelled")

                if websocket.open:
                    await websocket.send(
                        json.dumps({"event": "clear", "streamSid": stream_sid})
                    )
                await websocket.close()

        except Exception as e:
            print(f"[Error-{call_sid or 'unknown'}]: {e}")
        finally:
            print(f"[Cleanup-{call_sid}]: Cleaning up tasks and closing WebSocket")

            # Remove all files in AUDIO_DIR
            for filename in os.listdir(AUDIO_DIR):
                file_path = os.path.join(AUDIO_DIR, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        print(f"[Cleanup-{call_sid}]: Removed file {file_path}")
                except Exception as e:
                    print(f"[Cleanup-{call_sid}]: Error removing file {file_path}: {e}")

            handler_stop_event.set()

            # Cancel TTS task
            if tts_task and not tts_task.done():
                tts_stop_event.set()
                try:
                    await wait_for_tts_cleanup(tts_task)
                except Exception as e:
                    print(f"[Cleanup-{call_sid}]: Error waiting for TTS task: {e}")

            # Cancel silence detection
            if silence_task:
                silence_task.cancel()
                try:
                    await silence_task
                except asyncio.CancelledError:
                    print(f"[Cleanup-{call_sid}]: Silence task cancelled")
                except Exception as e:
                    print(f"[Cleanup-{call_sid}]: Silence task error: {e}")

            # Close WebSocket if not already closed
            try:
                if websocket.open:
                    await websocket.send(
                        json.dumps({"event": "clear", "streamSid": stream_sid})
                    )
                    await websocket.close()
            except Exception as e:
                print(f"[Cleanup-{call_sid}]: Error closing WebSocket: {e}")


# Entrypoint
async def main():
    print("WebSocket server running on port 8765...")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
