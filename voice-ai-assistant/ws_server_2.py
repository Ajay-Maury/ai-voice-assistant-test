import asyncio
import websockets
import json
import base64
import random
from utils.audio_utils import is_mulaw_silent

# --- Config & environment variables ---
from config.settings import (
    AI_SYSTEM_PROMPT,
    AUDIO_BUFFER_SILENCE,
    AUDIO_CHUNK_SIZE,
    MIN_AUDIO_BYTES,
    ENGAGEMENT_RESPONSES,
    OPENAI_API_KEY,
    OPENAI_TTS_VOICE,
    REDIS_URL,
    get_engagement_audio,
)

LOG_EVENT_TYPES = [
    "error",
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "session.created",
]

SYSTEM_MESSAGE = AI_SYSTEM_PROMPT
VOICE = OPENAI_TTS_VOICE

if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY")


# --- Safe WebSocket send ---
async def safe_send(ws, lock: asyncio.Lock, data: dict):
    try:
        msg = json.dumps(data)
        async with lock:
            await ws.send(msg)
        # print(f"[WS] Sent: {data.get('event')} | {data.get('mark') or ''}")
    except Exception as e:
        print(f"[WS][ERROR] Failed to send message: {e}")


async def say_with_ai(ai_ws, text: str, exact: bool = True):
    """
    Sends a message to the assistant to speak.

    Args:
        ai_ws: The websocket connected to the assistant.
        text (str): The message to be spoken by the assistant.
        exact (bool): If True, instructs the assistant to say the text verbatim.
    """
    prompt = f"Say exactly this to the user: {text}" if exact else text

    await ai_ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            }
        )
    )
    await ai_ws.send(json.dumps({"type": "response.create"}))


# --- Main handler ---
async def handler(websocket, path):
    print(f"[SERVER] New WebSocket connection established.")
    send_lock = asyncio.Lock()
    raw_buffer = b""
    call_sid = stream_sid = None
    tts_task = None
    tts_stop = asyncio.Event()
    handler_stop = asyncio.Event()
    last_audio_time = speech_start = 0.0
    last_backchannel = 0.0
    tts_type = None
    ai_talking=False

    async def engagement_monitor():
        nonlocal last_backchannel, speech_start, tts_task, tts_type, ai_talking
        print("[ENGAGE] Engagement monitor started.")
        silent_since = None
        last_engagement_time = 0  # Shared cooldown for both types
        COOLDOWN_SECONDS = 5

        while not handler_stop.is_set():
            await asyncio.sleep(0.5)
            now = asyncio.get_event_loop().time()
            talking = len(raw_buffer) > MIN_AUDIO_BYTES
            # tts_active = tts_task and not tts_task.done()
            print(f"len(raw_buffer)--{len(raw_buffer)}, --talking:--{talking}, speech_start:---{speech_start}, ai_talking:--- {ai_talking}")

            # Handle engaged responses (when user is speaking)
            if talking:
                silent_since = None
                if (
                    # not tts_active
                    # and 
                    speech_start > 0
                    and (now - speech_start >= 0.20)
                    and (now - last_engagement_time >= COOLDOWN_SECONDS)
                ):
                    text = random.choice(ENGAGEMENT_RESPONSES["ENGAGED"])
                    print(f"[ENGAGE] Triggered engaged response: {text}")
                    last_backchannel = now
                    last_engagement_time = now
                    tts_type = "engagement"
                    tts_stop.clear()
                    tts_task = asyncio.create_task(stream_tts_to_twilio(text))
                    await tts_task

            # Handle disengaged responses (if silent for a while)
            else:
                if silent_since is None:
                    silent_since = now
                elif (
                    now - silent_since >= 5
                    and not ai_talking  # 🔴 Suppress disengaged if AI is speaking
                    # and not tts_active
                    and (now - last_engagement_time >= COOLDOWN_SECONDS)
                ):
                    text = random.choice(ENGAGEMENT_RESPONSES["DISENGAGED"])
                    print(f"[ENGAGE] Triggered disengaged response: {text}")
                    last_backchannel = now
                    last_engagement_time = now
                    tts_type = "engagement"
                    tts_stop.clear()
                    tts_task = asyncio.create_task(stream_tts_to_twilio(text))
                    await tts_task

    async def barge_in_handler():
        nonlocal raw_buffer, last_audio_time, speech_start, tts_task, tts_type
        print("[STT] Barge-in handler started.")
        while not handler_stop.is_set():
            await asyncio.sleep(0.25)
            now = asyncio.get_event_loop().time()
            elapsed = now - last_audio_time

            if (
                len(raw_buffer) > MIN_AUDIO_BYTES
                and tts_type != "engagement"  # ✅ Skip barge-in if it's engagement TTS
                and ai_talking
            ):
                print("[STT][BARGE-IN] User barge-in detected. Interrupting TTS.")
                await safe_send(
                    websocket, send_lock, {"event": "clear", "streamSid": stream_sid}
                )
                await safe_send(
                    websocket,
                    send_lock,
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": "tts_interrupted"},
                    },
                )
                raw_buffer = b""

    async def receive_and_stream_ai():
        nonlocal call_sid, stream_sid, raw_buffer, speech_start, ai_talking
        barge_in_task = engagement_task = None
        conversation_history = []
        ai_text_fragments = []
        print("[WS-AI] Connecting to OpenAI realtime WS...")
        async with websockets.connect(
            "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01",
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1",
            },
        ) as ai_ws:

            print("[WS-AI] Connected to OpenAI.")
            await ai_ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "turn_detection": {"type": "server_vad"},
                            "input_audio_format": "g711_ulaw",
                            "output_audio_format": "g711_ulaw",
                            "voice": VOICE,
                            "instructions": SYSTEM_MESSAGE,
                            "modalities": ["text", "audio"],
                            "temperature": 0.8,
                        },
                    }
                )
            )

            # # ✅ Send initial greeting
            # print("[WS-AI] Sending initial greeting...")
            # text = "Greet the user with 'Hello there! I am an AI voice assistant. How can I help you?'"
            # await say_with_ai(ai_ws, text, exact=False)

            try:
                async for msg_str in websocket:
                    data = json.loads(msg_str)
                    evt = data.get("event")
                    # print("---received event---", evt)
                    if evt == "start":
                        call_sid = data["start"]["callSid"]
                        stream_sid = data["start"]["streamSid"]

                        engagement_task = asyncio.create_task(engagement_monitor())
                        barge_in_task = asyncio.create_task(barge_in_handler())

                        print(
                            f"[WS] Call START | Call SID: {call_sid}, Stream SID: {stream_sid}"
                        )

                    elif evt == "media":
                        chunk = base64.b64decode(data["media"]["payload"])
                        # Skip silent chunks
                        if not is_mulaw_silent(chunk):
                            # Append to raw buffer and reset silence timer
                            raw_buffer += chunk

                            now = asyncio.get_event_loop().time()
                            if speech_start == 0.0:
                                speech_start = now
                            last_audio_time = now

                        await ai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": data["media"]["payload"],
                                }
                            )
                        )
                        # print(f"[WS] Received audio chunk ({len(chunk)} bytes)")

                    elif evt == "stop":
                        print(f"[WS] Call STOP received.")
                        handler_stop.set()
                        break

                    try:
                        while True:
                            ai_msg = await asyncio.wait_for(ai_ws.recv(), timeout=0.01)
                            print(f"[AI-RESPONSE]----: {ai_msg}")
                            o = json.loads(ai_msg)
                            if o.get("type") == "input.audio_transcript.done":
                                transcript = o.get("transcript", "").strip()
                                print(f"----[HISTORY] User (transcript)----: {transcript}")

                            elif o.get("type") == "response.audio.delta" and o.get("delta"):
                                payload = o["delta"]
                                print("----Getting response audio------")
                                ai_talking = True
                                payload_b64 = base64.b64encode(base64.b64decode(payload)).decode()
                                await safe_send(
                                    websocket,
                                    send_lock,
                                    {
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": payload_b64},
                                    },
                                )

                            elif o.get("type") == "response.output_item.done":
                                item = o.get("item", {})
                                role = item.get("role")
                                content = item.get("content", [])
                                print(f"--role--: {role}, --content---: {content}")

                            elif o.get("type") == "response.done":
                                ai_talking = False
                                raw_buffer = b""
                                await safe_send(
                                    websocket,
                                    send_lock,
                                    {
                                        "event": "mark",
                                        "streamSid": stream_sid,
                                        "mark": {"name": "ai_reply_complete"},
                                    },
                                )
                            # print("[DEBUG] Received AI WS msg:", ai_msg)  # ✅ Keep this here
                            # o = json.loads(ai_msg)
                            # if o.get("type") == "response.audio.delta" and o.get(
                            #     "delta"
                            # ):
                            #     payload = o["delta"]
                            #     print(f"----Getting response audio------")
                            #     ai_talking = True  # ✅ AI is speaking
                            #     payload_b64 = base64.b64encode(
                            #         base64.b64decode(payload)
                            #     ).decode()
                            #     await safe_send(
                            #         websocket,
                            #         send_lock,
                            #         {
                            #             "event": "media",
                            #             "streamSid": stream_sid,
                            #             "media": {"payload": payload_b64},
                            #         },
                            #     )

                            # elif o.get("type") == "response.output_item.done":
                            #     item = o.get("item", {})
                            #     role = item.get("role")
                            #     content = item.get("content", [])
                            #     print(f"--role--: {role}, --content---: {content}")
                            #     if role == "assistant":
                            #         text_parts = [c["transcript"] for c in content if c["type"] == "audio"]
                            #         full_text = " ".join(text_parts).strip()
                            #         # if full_text:
                            #             # print(f"[HISTORY] Assistant (final): {full_text}")
                            #             # conversation_history.append({"role": "assistant", "text": full_text})

                            
                            # # elif o.get("type") == "response.audio_transcript.done":
                            # #     transcript = o.get("transcript", "").strip()
                            # #     if transcript:
                            # #         print(f"[HISTORY] User (transcript): {transcript}")
                            # #         conversation_history.append({"role": "user", "text": transcript})

                            # elif o.get("type") == "input.audio_transcript.done":
                            #     transcript = o.get("transcript", "").strip()
                            #     print(f"----[HISTORY] User (transcript)----: {transcript}")
                            #     # if transcript:
                            #     #     conversation_history.append({"role": "user", "text": transcript})

                            # elif o.get("type") == "response.done":
                            #     await safe_send(
                            #         websocket,
                            #         send_lock,
                            #         {
                            #             "event": "mark",
                            #             "streamSid": stream_sid,
                            #             "mark": {"name": "ai_reply_complete"},
                            #         },
                            #     )
                            #     # await safe_send(
                            #     #     websocket,
                            #     #     send_lock,
                            #     #     {
                            #     #         "event": "mark",
                            #     #         "streamSid": stream_sid,
                            #     #         "mark": {"name": "ai_reply_complete_cleanup"},
                            #     #     },
                            #     # )
                            #     ai_talking = False  # ✅ AI is not speaking
                            #     raw_buffer = b""


                            #     # print("\n========== FULL CONVERSATION ==========")
                            #     # for turn in conversation_history:
                            #     #     print(f"{turn['role'].capitalize()}: {turn['text']}")
                            #     #     print("========================================\n")


                    except asyncio.TimeoutError:
                        pass
            except websockets.exceptions.ConnectionClosed:
                print("[WS] Client disconnected cleanly.")
            except Exception as e:
                print(f"[WS ERROR] {e}")
            finally:
                if barge_in_task:
                    barge_in_task.cancel()
                if engagement_task:
                    engagement_task.cancel()
                print("[HANDLER] Session cleanup complete.")

    # --- Engagement TTS streaming ---
    async def stream_tts_to_twilio(text: str):
        nonlocal tts_type
        tts_type = "engagement"
        print(f"[TTS] Streaming pre-generated audio to Twilio... for text: {text[:60]}")

        # await asyncio.sleep(0.5)  # Let Twilio prep

        try:
            audio_path = await get_engagement_audio(text)
            with open(audio_path, "rb") as f:
                audio_data = f.read()
        except Exception as e:
            print(f"[TTS] Error fetching cached engagement audio: {e}")
            return

        # # clear previous audio stream
        # await safe_send(
        #     websocket, send_lock, {"event": "clear", "streamSid": stream_sid}
        # )

        chunk_count = 0
        for i in range(0, len(audio_data), AUDIO_CHUNK_SIZE):
            if tts_stop.is_set():
                print("[TTS] TTS interrupted mid-stream.")
                break
            sub = audio_data[i : i + AUDIO_CHUNK_SIZE]
            b64 = base64.b64encode(sub).decode()
            if stream_sid:
                await safe_send(
                    websocket,
                    send_lock,
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": b64},
                    },
                )
                await asyncio.sleep(0.02)
            chunk_count += 1

        print("[TTS] Cached TTS stream ended.")
        await safe_send(
            websocket,
            send_lock,
            {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": "tts_complete"},
            },
        )
        await asyncio.sleep(0.3)
        tts_type = None

    await receive_and_stream_ai()


# --- Start WebSocket server ---
async def main():
    print("[SERVER] WebSocket server listening on port 8765...")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
