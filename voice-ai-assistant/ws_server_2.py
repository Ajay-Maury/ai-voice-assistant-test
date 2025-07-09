import asyncio
import websockets
import json
import base64
import os
import random
from typing import List
import aiohttp
import redis

# --- Config & environment variables ---
from config.settings import (
    AI_SYSTEM_PROMPT, AUDIO_BUFFER_SILENCE, AUDIO_CHUNK_SIZE,
    MIN_AUDIO_BYTES, ENGAGEMENT_RESPONSES,
    OPENAI_API_KEY, OPENAI_TTS_VOICE, REDIS_URL
)

LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]

SYSTEM_MESSAGE = AI_SYSTEM_PROMPT
VOICE = OPENAI_TTS_VOICE

if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY")

# --- Redis-based context storage ---
redis_client = redis.from_url(REDIS_URL)

def get_context(call_sid: str) -> List[dict]:
    print(f"[CTX] Fetching context for Call SID: {call_sid}")
    raw = redis_client.get(call_sid)
    context = json.loads(raw) if raw else []
    # print(f"[CTX] Context retrieved: {context}")
    return context

def store_context(call_sid: str, user_msg: str, ai_msg: str):
    print(f"[CTX] Storing new interaction to context for {call_sid}")
    ctx = get_context(call_sid)
    ctx.append({"user": user_msg, "ai": ai_msg})
    redis_client.set(call_sid, json.dumps(ctx[-20:]))
    # print(f"[CTX] Context stored. Total turns: {len(ctx[-20:])}")

# --- AI response generation ---
async def get_ai_response(user_text: str, context: List[dict]) -> str:
    print(f"[AI] Preparing prompt with context for user text: {user_text}")
    prompt = ""
    for turn in context:
        prompt += f"User: {turn['user']}\nAI: {turn['ai']}\n"
    prompt += f"User: {user_text}\nAI:"

    async with aiohttp.ClientSession() as session:
        try:
            print("[AI] Sending prompt to OpenAI...")
            resp = await session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4o-realtime-preview-2024-10-01",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "stream": False
                }
            )
            data = await resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            print(f"[AI] Received reply: {reply}")
            return reply
        except Exception as e:
            print(f"[AI][ERROR] Failed to get AI response: {e}")
            return "Sorry, I encountered an issue responding."

# --- TTS generator ---
async def get_ai_tts_stream(text: str):
    print(f"[TTS] Requesting TTS for text: {text[:60]}...")
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2"
    }
    payload = {"model": "tts-1", "voice": VOICE, "input": text, "response_format": "ulaw"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            print(f"[TTS] TTS stream started...")
            async for chunk in resp.content.iter_chunked(1024):
                yield chunk
    print("[TTS] TTS stream ended.")

# --- Safe WebSocket send ---
async def safe_send(ws, lock: asyncio.Lock, data: dict):
    try:
        msg = json.dumps(data)
        async with lock:
            await ws.send(msg)
        print(f"[WS] Sent: {data.get('event')} | {data.get('mark') or ''}")
    except Exception as e:
        print(f"[WS][ERROR] Failed to send message: {e}")

# --- Main handler ---
async def handler(websocket, path):
    print(f"[SERVER] New WebSocket connection established.")
    send_lock = asyncio.Lock()
    buffer = raw_buffer = b""
    call_sid = stream_sid = None
    tts_task = None
    tts_stop = asyncio.Event()
    handler_stop = asyncio.Event()
    last_audio_time = speech_start = 0.0
    last_backchannel = 0.0
    tts_type = None

    async def engagement_monitor():
        nonlocal last_backchannel, speech_start, tts_task, tts_type
        print("[ENGAGE] Engagement monitor started.")
        silent_since = None
        while not handler_stop.is_set():
            await asyncio.sleep(1)
            now = asyncio.get_event_loop().time()
            talking = len(raw_buffer) > MIN_AUDIO_BYTES
            tts_active = tts_task and not tts_task.done()

            if talking:
                silent_since = None
                if speech_start and now - speech_start >= 1.5 and now - last_backchannel >= 1.5 and not tts_active:
                    text = random.choice(ENGAGEMENT_RESPONSES["ENGAGED"])
                    print(f"[ENGAGE] Triggered engaged response: {text}")
                    last_backchannel = now
                    tts_type = "engagement"
                    tts_stop.clear()
                    tts_task = asyncio.create_task(stream_tts_to_twilio(text))
            else:
                if silent_since is None:
                    silent_since = now
                elif now - silent_since >= 5 and not tts_active:
                    text = random.choice(ENGAGEMENT_RESPONSES["DISENGAGED"])
                    print(f"[ENGAGE] Triggered disengaged response: {text}")
                    last_backchannel = now
                    tts_type = "engagement"
                    tts_stop.clear()
                    tts_task = asyncio.create_task(stream_tts_to_twilio(text))

    async def silence_detector():
        nonlocal buffer, raw_buffer, last_audio_time, speech_start, tts_task, tts_type
        print("[STT] Silence detector started.")
        while not handler_stop.is_set():
            await asyncio.sleep(0.25)
            now = asyncio.get_event_loop().time()
            elapsed = now - last_audio_time

            if raw_buffer and tts_task and not tts_task.done() and tts_type == "ai_reply":
                print("[STT][BARGE-IN] User barge-in detected. Interrupting TTS.")
                tts_stop.set()
                try:
                    await tts_task
                except Exception as e:
                    print(f"[STT][ERROR] Failed to stop TTS: {e}")
                await safe_send(websocket, send_lock, {"event": "clear", "streamSid": stream_sid})
                await safe_send(websocket, send_lock, {
                    "event": "mark", "streamSid": stream_sid, "mark": {"name": "tts_interrupted"}
                })
                raw_buffer = b""

            if raw_buffer and elapsed >= AUDIO_BUFFER_SILENCE:
                print(f"[STT] Silence threshold hit. Sending to AI.")
                payload_b64 = base64.b64encode(buffer).decode()
                buffer = raw_buffer = b""
                speech_start = 0.0
                ctx = get_context(call_sid)
                user_text = "<audio>"  # Placeholder
                ai_text = await get_ai_response(user_text, ctx)
                store_context(call_sid, user_text, ai_text)
                tts_stop.clear()
                tts_type = "ai_reply"
                tts_task = asyncio.create_task(stream_tts_to_twilio(ai_text))

    async def receive_and_stream_ai():
        nonlocal call_sid, stream_sid, buffer, raw_buffer, speech_start
        print("[WS-AI] Connecting to OpenAI realtime WS...")
        async with websockets.connect(
            'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }
        ) as ai_ws:
            print("[WS-AI] Connected to OpenAI.")
            await ai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "turn_detection": {"type": "server_vad"},
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "voice": VOICE,
                    "instructions": SYSTEM_MESSAGE,
                    "modalities": ["text", "audio"],
                    "temperature": 0.8
                }
            }))

            # ✅ Send initial greeting
            print("[WS-AI] Sending initial greeting...")
            await ai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Greet the user with 'Hello there! I am an AI voice assistant. How can I help you?'"
                        }
                    ]
                }
            }))
            await ai_ws.send(json.dumps({"type": "response.create"}))

            engagement_task = asyncio.create_task(engagement_monitor())
            silence_task = asyncio.create_task(silence_detector())

            try:
                async for msg_str in websocket:
                    data = json.loads(msg_str)
                    evt = data.get("event")
                    if evt == "start":
                        call_sid = data["start"]["callSid"]
                        stream_sid = data["start"]["streamSid"]
                        print(f"[WS] Call START | Call SID: {call_sid}, Stream SID: {stream_sid}")

                    elif evt == "media":
                        chunk = base64.b64decode(data["media"]["payload"])
                        buffer += chunk
                        raw_buffer += chunk
                        now = asyncio.get_event_loop().time()
                        if speech_start == 0.0:
                            speech_start = now
                        last_audio_time = now
                        await ai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"]
                        }))
                        # print(f"[WS] Received audio chunk ({len(chunk)} bytes)")

                    elif evt == "stop":
                        print(f"[WS] Call STOP received.")
                        handler_stop.set()
                        break

                    try:
                        while True:
                            ai_msg = await asyncio.wait_for(ai_ws.recv(), timeout=0.01)
                            o = json.loads(ai_msg)
                            if o.get("type") == "response.audio.delta" and o.get("delta"):
                                payload = o["delta"]
                                payload_b64 = base64.b64encode(base64.b64decode(payload)).decode()
                                await safe_send(websocket, send_lock, {
                                    "event": "media", "streamSid": stream_sid,
                                    "media": {"payload": payload_b64}
                                })

                            elif o.get("type") == "response.done":
                                print("[WS-AI] TTS response complete.")
                                await safe_send(websocket, send_lock, {
                                    "event": "mark", "streamSid": stream_sid,
                                    "mark": {"name": "tts_complete"}
                                })
                    except asyncio.TimeoutError:
                        pass
            finally:
                silence_task.cancel()
                engagement_task.cancel()
                print("[HANDLER] Session cleanup complete.")

    async def stream_tts_to_twilio(text: str):
        print(f"[TTS] Starting stream to Twilio...")
        generator = get_ai_tts_stream(text)
        async for chunk in generator:
            if tts_stop.is_set():
                print("[TTS] TTS interrupted mid-stream.")
                break
            for i in range(0, len(chunk), AUDIO_CHUNK_SIZE):
                sub = chunk[i:i + AUDIO_CHUNK_SIZE]
                b64 = base64.b64encode(sub).decode()
                await safe_send(websocket, send_lock, {
                    "event": "media", "streamSid": stream_sid,
                    "media": {"payload": b64}
                })
                await asyncio.sleep(0.02)
        else:
            print("[TTS] TTS fully streamed to Twilio.")
            await safe_send(websocket, send_lock, {
                "event": "mark", "streamSid": stream_sid,
                "mark": {"name": "tts_complete"}
            })

    await receive_and_stream_ai()

# --- Start WebSocket server ---
async def main():
    print("[SERVER] WebSocket server listening on port 8765...")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
