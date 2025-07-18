import asyncio
import os
import websockets
import json
import base64

# Internal utilities
from utils.redis_utils import get_context, store_context
from utils.sarvam_utils import synthesize_mulaw_sarvam_tts
from utils.audio_utils import is_silent_mulaw_audio, convert_mulaw_to_wav
from utils.open_ai_utils import get_ai_response, transcribe_audio_whisper_groq

# Config values
from config.settings import (
    AUDIO_BUFFER_SILENCE,
    AUDIO_CHUNK_DIR,
    AUDIO_CHUNK_SIZE,
    DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY,
    DISENGAGEMENT_TRIGGER_SECONDS,
    ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY,
    ENGAGEMENT_TRIGGER_SECONDS,
    MIN_AUDIO_BYTES,
    SILENCE_MAX_DURATION,
    TAVILY_API_KEY
)

from utils.utils import get_engagement_response


# Await the TTS task safely and shield from cancellation
async def wait_for_tts_finish(tts_task):
    try:
        await asyncio.shield(tts_task)
    except Exception as e:
        print(f"[TTS Cleanup Error]: {e}")


# Stream TTS audio to client in chunks and send a completion mark at the end
async def stream_tts_to_client(websocket, stream_sid, text, call_sid, stop_event, mark_name=None):
    print(f"[TTS-{call_sid}]: Generating TTS for: {text}")
    try:
        audio_chunk = await synthesize_mulaw_sarvam_tts(text)
    except Exception as e:
        print(f"[TTS-{call_sid}]: TTS synthesis error: {e}")
        return

    if not audio_chunk:
        print(f"[TTS-{call_sid}]: No audio received from TTS service")
        return

    # Send audio in chunks
    for i in range(0, len(audio_chunk), AUDIO_CHUNK_SIZE):
        if stop_event.is_set():
            print(f"[TTS-{call_sid}]: Playback interrupted by user")
            break

        chunk = audio_chunk[i: i + AUDIO_CHUNK_SIZE]
        try:
            await websocket.send(json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(chunk).decode()},
            }))
        except websockets.exceptions.ConnectionClosed:
            print(f"[TTS-{call_sid}]: WebSocket connection closed during playback")
            return

        await asyncio.sleep(0.01)  # ~10ms delay between chunks

    # Send a "mark" after TTS is done (Twilio will echo it back)
    if not stop_event.is_set():
        await websocket.send(json.dumps({
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": f"{mark_name}_tts_complete" if mark_name else "tts_complete"},
        }))


# Monitor silence or speech to detect user engagement/disengagement
async def monitor_user_engagement(websocket, stream_sid, call_sid, stop_event, raw_buffer_ref, tts_task_ref, tts_stop_event_ref, speech_start_ref, twilio_mark_name_ref):
    print(f"[Engagement-{call_sid}]: Starting user engagement monitor")

    last_engaged_time, last_disengaged_time = 0, 0
    silent_since = None

    while not stop_event.is_set():
        await asyncio.sleep(0.50)  # Poll every 500ms
        now = asyncio.get_event_loop().time()

        user_is_talking = len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES
        tts_active = tts_task_ref[0] and not tts_task_ref[0].done()
        print("twilio_mark_name_ref---:",twilio_mark_name_ref[0],'-------')

        if user_is_talking:
            silent_since = None  # Cancel silence tracking

            # Track start of current user speech
            if speech_start_ref[0] == 0:
                speech_start_ref[0] = now

            time_speaking = now - speech_start_ref[0]
            last_disengaged_time = 0

            # If user talks long enough or it's time to repeat, send engagement
            if (
                (last_engaged_time == 0 and time_speaking >= ENGAGEMENT_TRIGGER_SECONDS) or
                (last_engaged_time > 0 and (now - last_engaged_time) >= ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY)
            ) and not tts_active:

                text = get_engagement_response("ENGAGED", "hi")
                print(f"[Engagement-{call_sid}]: Sending engaged response: '{text}'")

                tts_stop_event_ref.clear()
                twilio_mark_name_ref[0] = "engagement_response"
                tts_task_ref[0] = asyncio.create_task(
                    stream_tts_to_client(websocket, stream_sid, text, call_sid, tts_stop_event_ref, mark_name="engagement_response")
                )
                last_engaged_time = now

        elif twilio_mark_name_ref[0] and (twilio_mark_name_ref[0] == "engagement_response_tts_complete" or    not twilio_mark_name_ref[0].endswith("tts_complete")):
            silent_since = None  # TTS still playing, ignore silence
            last_disengaged_time = now

        else:
            if silent_since is None:
                silent_since = now
                speech_start_ref[0] = 0  # Reset speech tracking

            time_silent = now - silent_since
            last_engaged_time = 0

            # print(f"now--: {now}, silent_since--: {silent_since}, time_silent--: {time_silent}, DISENGAGEMENT_TRIGGER_SECONDS---: {DISENGAGEMENT_TRIGGER_SECONDS}, last_disengaged_time--: {last_disengaged_time}, now - last_disengaged_time--: {now - last_disengaged_time}")
            # If silence persists, send disengaged prompt
            if (
                (last_disengaged_time == 0 and time_silent >= DISENGAGEMENT_TRIGGER_SECONDS) or
                (last_disengaged_time > 0 and (now - last_disengaged_time) >= DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY)
            ) and not tts_active:

                text = get_engagement_response("DISENGAGED", "hi")
                print(f"[Engagement-{call_sid}]: Sending disengaged response: '{text}'")

                tts_stop_event_ref.clear()
                twilio_mark_name_ref[0] = "disengagement_response"
                tts_task_ref[0] = asyncio.create_task(
                    stream_tts_to_client(websocket, stream_sid, text, call_sid, tts_stop_event_ref, mark_name="disengagement_response")
                )
                last_disengaged_time = now


# Detect silence and barge-in during user response
async def detect_silence_and_respond(websocket, stream_sid, call_sid, buffer_ref, raw_buffer_ref, stop_event, last_audio_time_ref, tts_task_ref, tts_stop_event_ref, speech_start_ref, twilio_mark_name_ref):
    print(f"[Silence-{call_sid}]: Starting silence and barge-in monitor")

    while not stop_event.is_set():
        await asyncio.sleep(0.25)
        now = asyncio.get_event_loop().time()
        elapsed = now - last_audio_time_ref[0]

        # If user speaks while TTS is playing, it's a barge-in
        if len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES and tts_task_ref[0] and not tts_task_ref[0].done() and not (twilio_mark_name_ref[0] == "engagement_response" or twilio_mark_name_ref[0] == "ai_greet_response"):
            print(f"[Barge-in-{call_sid}]: User interrupted AI TTS")
            tts_stop_event_ref.set()
            await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
            await websocket.send(json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": "tts_interrupted"}}))

        # Detect end of user speech by checking silence duration
        elif len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES and elapsed >= AUDIO_BUFFER_SILENCE:
            print(f"[Silence-{call_sid}]: Silence detected after {elapsed:.2f}s, transcribing...")

            try:
                twilio_mark_name_ref[0] = "ai_response"
                audio_file = convert_mulaw_to_wav(call_sid, raw_buffer_ref[0])

                buffer_ref[0], raw_buffer_ref[0] = b"", b""
                speech_start_ref[0] = 0

                whisper_result = transcribe_audio_whisper_groq(audio_file, "hi")
                if whisper_result:
                    os.remove(audio_file)

                user_text = whisper_result if isinstance(whisper_result, str) else whisper_result.get("text")
                if not user_text:
                    continue

                print(f"[User-{call_sid}]: {user_text}")

                context = get_context(call_sid)
                ai_response = await get_ai_response(user_text, context, call_sid)
                store_context(call_sid, user_text, ai_response)

                # Wait if there's still a running TTS
                if tts_task_ref[0] and not tts_task_ref[0].done():
                    print(f"[AI-TTS-{call_sid}]: Waiting for previous TTS to finish")
                    await wait_for_tts_finish(tts_task_ref[0])

                tts_stop_event_ref.clear()
                tts_task_ref[0] = asyncio.create_task(
                    stream_tts_to_client(websocket, stream_sid, ai_response, call_sid, tts_stop_event_ref, mark_name="ai_response")
                )

                await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))

            except Exception as e:
                twilio_mark_name_ref = [None]
                print(f"[Silence-{call_sid}]: Error during processing: {e}")


# --- WebSocket Handler ---
async def websocket_handler(websocket):
    print("[+] Client connected to WebSocket")

    # State references
    call_sid, stream_sid = None, None
    buffer_ref, raw_buffer_ref = [b""], [b""]
    tts_task_ref = [None]
    tts_stop_event = asyncio.Event()
    stop_event = asyncio.Event()
    last_audio_time_ref = [asyncio.get_event_loop().time()]
    speech_start_ref = [0]
    twilio_mark_name_ref = [None]

    silence_task, engagement_task = None, None

    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                print(f"[Start]: callSid={call_sid}, streamSid={stream_sid}")

                # Launch silence and engagement detection tasks
                silence_task = asyncio.create_task(
                    detect_silence_and_respond(websocket, stream_sid, call_sid, buffer_ref, raw_buffer_ref, stop_event,
                                               last_audio_time_ref, tts_task_ref, tts_stop_event, speech_start_ref, twilio_mark_name_ref))

                engagement_task = asyncio.create_task(
                    monitor_user_engagement(websocket, stream_sid, call_sid, stop_event,
                                            raw_buffer_ref, tts_task_ref, tts_stop_event, speech_start_ref, twilio_mark_name_ref))

            elif event == "media":
                if not call_sid:
                    continue

                audio_chunk = base64.b64decode(data["media"]["payload"])
                buffer_ref[0] += audio_chunk

                now = asyncio.get_event_loop().time()
                is_speech = not is_silent_mulaw_audio(audio_chunk)

                # Append valid audio to raw buffer
                if is_speech:
                    raw_buffer_ref[0] += audio_chunk
                    last_audio_time_ref[0] = now

                    if speech_start_ref[0] == 0:
                        speech_start_ref[0] = int(now)
                elif (now - last_audio_time_ref[0]) < SILENCE_MAX_DURATION:
                    raw_buffer_ref[0] += audio_chunk

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name")
                if mark_name:
                    twilio_mark_name_ref[0] = mark_name
                    print(f"[Mark-{call_sid}]: Received twilio mark: {twilio_mark_name_ref}")
                    if mark_name in ("tts_complete", "ai_greet_response_tts_complete", "ai_response_tts_complete"):
                        tts_stop_event.set()

    except Exception as e:
        print(f"[WebSocket-{call_sid}]: Error occurred: {e}")

    finally:
        print(f"[Cleanup-{call_sid}]: Performing cleanup")
        stop_event.set()

        # Gracefully shut down TTS
        if tts_task_ref[0] and not tts_task_ref[0].done():
            tts_stop_event.set()
            await wait_for_tts_finish(tts_task_ref[0])

        if silence_task:
            silence_task.cancel()
            try: await silence_task
            except asyncio.CancelledError:
                print(f"[Cleanup-{call_sid}]: Silence task cancelled")

        if engagement_task:
            engagement_task.cancel()
            try: await engagement_task
            except asyncio.CancelledError:
                print(f"[Cleanup-{call_sid}]: Engagement task cancelled")

        # Delete cached audio files
        for filename in os.listdir(AUDIO_CHUNK_DIR):
            if f"{call_sid}_" in filename:
                try:
                    os.remove(os.path.join(AUDIO_CHUNK_DIR, filename))
                except Exception as e:
                    print(f"[Cleanup-{call_sid}]: File removal error: {e}")

        try:
            await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
            await websocket.close()
        except websockets.exceptions.ConnectionClosedOK:
            print(f"[Cleanup-{call_sid or 'Unknown'}]: WebSocket already closed gracefully.")
        except Exception as e:
            print(f"[Cleanup-{call_sid or 'Unknown'}]: WebSocket close error: {e}")


# --- Start Server ---

async def main():
    print("WebSocket server is running on port 8765...")
    async with websockets.serve(websocket_handler, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
