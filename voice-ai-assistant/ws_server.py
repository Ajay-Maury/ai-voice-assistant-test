import asyncio
import websockets
import json
import base64
import os
from utils.audio_utils import save_audio_chunk, transcribe_audio
from utils.ai_utils import get_ai_response
from utils.azure_tts import synthesize_azure_tts_to_pcm
from utils.redis_utils import get_context, store_context

# TTS Streaming
async def stream_tts_audio(websocket, stream_sid, audio_bytes, call_sid, stop_event):
    chunk_size = 160  # 20ms of 8kHz mu-law audio
    for i in range(0, len(audio_bytes), chunk_size):
        if stop_event.is_set():
            print(f"[TTS-{call_sid}]: Playback interrupted by user")
            break
        chunk = audio_bytes[i:i + chunk_size]
        await websocket.send(json.dumps({
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "payload": base64.b64encode(chunk).decode()
            }
        }))
        await asyncio.sleep(0.02)

    if not stop_event.is_set():
        await websocket.send(json.dumps({
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": "tts_complete"}
        }))


async def wait_for_tts_cleanup(task):
    try:
        print("[TTS Cleanup]: Waiting for TTS task to finish")
        await asyncio.shield(task)
    except Exception as e:
        print(f"-----[TTS Cleanup Error]------: {e}")


# Main WebSocket handler
async def handler(websocket, path):
    print("[+] WebSocket connected")
    buffer = b""
    call_sid = None
    stream_sid = None
    tts_task = None
    tts_stop_event = asyncio.Event()

    async for message in websocket:
        try:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                print(f"[+] Stream start – callSid={call_sid}, streamSid={stream_sid}")

            elif event == "media":
                if not call_sid:
                    continue

                audio_b64 = data["media"]["payload"]
                new_chunk = base64.b64decode(audio_b64)
                buffer += new_chunk

                # 🔄 Process every ~1 sec of audio (8kHz × 1s = 8000 bytes)
                if len(buffer) >= 8000 * 1:  # 1 second of audio
                    audio_file = save_audio_chunk(call_sid, buffer)
                    buffer = b""
                    text = transcribe_audio(audio_file)
                    if not text:
                        continue

                    print(f"------[User-{call_sid}]-----: {text}")

                    # 🔇 Barge-in: User spoke during TTS playback
                    if text and tts_task and not tts_task.done():
                        print(f"[Barge-In-{call_sid}]: User spoke during TTS playback, interrupting")
                        tts_stop_event.set()

                        # 🧹 Clean up the current TTS task
                        await wait_for_tts_cleanup(tts_task)

                        # 🧽 Clear TTS playback buffer
                        if websocket.open:
                            await websocket.send(json.dumps({
                                "event": "clear",
                                "streamSid": stream_sid
                            }))
                            await websocket.send(json.dumps({
                                "event": "mark",
                                "streamSid": stream_sid,
                                "mark": {"name": "tts_interrupted"}
                            }))
                            print(f"[TTS-{call_sid}]: Sent 'clear' and 'tts_interrupted' after barge-in")

                    # 💬 AI + TTS
                    context = get_context(call_sid)
                    ai_reply = get_ai_response(text, context)
                    print("---AI Reply-----", ai_reply)
                    store_context(call_sid, text, ai_reply)

                    tts_audio = synthesize_azure_tts_to_pcm(ai_reply)
                    if tts_audio:
                        tts_stop_event.clear()
                        tts_task = asyncio.create_task(
                            stream_tts_audio(websocket, stream_sid, tts_audio, call_sid, tts_stop_event)
                        )

            elif event == "stop":
                print(f"[+] Stream stopped for callSid={call_sid}")
                if tts_task and not tts_task.done():
                    tts_stop_event.set()
                    await tts_task
                if websocket.open:
                    await websocket.send(json.dumps({
                        "event": "clear",
                        "streamSid": stream_sid
                    }))
                await websocket.close()

        except Exception as e:
            print(f"[Error-{call_sid or 'unknown'}]: {e}")


# Server entrypoint
async def main():
    print("WebSocket server running on port 8765...")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
