import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional
import websockets
import json
import base64

import webrtcvad
from scipy.signal import resample

# Internal utilities
from utils.redis_utils import get_context, store_context
from utils.sarvam_utils import synthesize_mulaw_sarvam_tts
from utils.audio_utils import is_silent_mulaw_audio, convert_mulaw_to_wav, is_voiced
from utils.open_ai_utils import (
    get_ai_response,
    is_user_engagement,
    transcribe_audio_whisper_groq,
)

# Config values
from config.settings import (
    AUDIO_BUFFER_SILENCE,
    AUDIO_CACHE_DIR,
    AUDIO_CHUNK_DIR,
    AUDIO_CHUNK_SIZE,
    DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY,
    DISENGAGEMENT_TRIGGER_SECONDS,
    ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY,
    ENGAGEMENT_TRIGGER_SECONDS,
    INITIAL_GREETING_TEXT,
    MIN_AUDIO_BYTES,
    SILENCE_MAX_DURATION,
    TAVILY_API_KEY,
    VAD_FRAME_SIZE,
    VAD_MIN_SILENCE_FRAMES,
)

from utils.utils import get_engagement_response

# WebRTC VAD instance
vad = webrtcvad.Vad(2)  # Aggressiveness: 0–3


# Await the TTS task safely and shield from cancellation
async def wait_for_tts_finish(tts_task):
    try:
        await asyncio.shield(tts_task)
    except Exception as e:
        print(f"[TTS Cleanup Error]: {e}")


# Get mulaw audio buffer from TTS
async def generate_mulaw_audio_buffer(text: str) -> bytes:
    """
    Generate TTS mulaw audio for a given text.
    Returns raw mulaw audio buffer.
    """
    try:
        audio_chunk = await synthesize_mulaw_sarvam_tts(text)
        return audio_chunk  # bytes
    except Exception as e:
        print(f"[TTS] Error generating audio: {e}")
        return b""


# Stream mulaw audio buffer to Twilio via WebSocket
async def play_audio_buffer_to_twilio(
    websocket,
    stream_sid: str,
    audio_buffer: bytes,
    stop_event: asyncio.Event,
    mark_name: Optional[str] = None,
    mark_type: Optional[str] = "response",
):
    """
    Stream mulaw audio buffer to Twilio via WebSocket.
    Sends audio in small chunks and emits a `mark` at the end.
    """
    if not audio_buffer:
        print("[TTS] Empty audio buffer. Skipping playback.")
        return

    for i in range(0, len(audio_buffer), AUDIO_CHUNK_SIZE):
        if stop_event.is_set():
            print("[TTS] Playback interrupted by user.")
            break

        chunk = audio_buffer[i : i + AUDIO_CHUNK_SIZE]
        try:
            await websocket.send(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": base64.b64encode(chunk).decode()},
                    }
                )
            )
        except Exception as e:
            print("[TTS] WebSocket send error:", e)
            break

        await asyncio.sleep(0.01)  # 10ms pacing

    print(
        f"stop_event.is_set()---: {stop_event.is_set()}, mark_name---: {mark_name}, stream_sid---: {stream_sid}"
    )
    if not stop_event.is_set() and mark_name:
        await websocket.send(
            json.dumps(
                {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": f"{mark_name}_tts_complete"},
                }
            )
        )


# Stream TTS audio to client in chunks and send a completion mark at the end
async def stream_tts_to_client(
    websocket, stream_sid, text, call_sid, stop_event, mark_name=None, mark_type: Optional[str] = "response"
):
    """
    Stream TTS audio to Twilio WebSocket.
    Generates mulaw audio and sends it in chunks.
    """
    print(f"[TTS-{call_sid}]: Starting TTS for text: {text}")

    # Generate mulaw audio buffer
    audio_buffer = await generate_mulaw_audio_buffer(text)
    if not audio_buffer:
        print(f"[TTS-{call_sid}]: No audio generated for text: {text}")
        return

    # Play the audio buffer to Twilio
    await play_audio_buffer_to_twilio(
        websocket, stream_sid, audio_buffer, stop_event, mark_name, mark_type= mark_type
    )
    print(f"[TTS-{call_sid}]: Finished streaming TTS for text: {text}")


async def monitor_user_engagement(
    websocket,
    stream_sid,
    call_sid,
    stop_event,
    raw_buffer_ref,
    engagement_tts_task_ref,
    engagement_tts_stop_event_ref,
    response_tts_task_ref,
    response_tts_stop_event_ref,
    speech_start_ref,
    engagement_mark_name_ref,
    response_mark_name_ref,
    barge_in_detected_ref,
):
    print(f"[Engagement-{call_sid}]: Starting user engagement monitor")

    last_engaged_time = 0
    last_disengaged_time = 0
    silent_since = None

    while not stop_event.is_set():
        await asyncio.sleep(0.50)  # Poll every 500ms
        now = asyncio.get_event_loop().time()

        user_is_talking = len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES
        tts_active = (engagement_tts_task_ref[0] and not engagement_tts_task_ref[0].done()) or (response_tts_task_ref[0] and not response_tts_task_ref[0].done())

        print(f"[Engagement-{call_sid}][Loop] ─────")
        print(f"🧠 engagement_mark_name_ref: {engagement_mark_name_ref[0]}")
        print(f"🧠 response_mark_name_ref: {response_mark_name_ref[0]}")
        print(f"🎙️ user_is_talking: {user_is_talking}, 🗣️ TTS Active: {tts_active}, 🧏 Barge-In: {barge_in_detected_ref[0]}")
        print(f"📦 Buffer size: {len(raw_buffer_ref[0])} bytes")

        if user_is_talking:
            print(f"[Engagement-{call_sid}]: ✅ User is speaking")

            silent_since = None
            # twilio_mark_name_ref[0] = "user_speech"

            if speech_start_ref[0] == 0:
                speech_start_ref[0] = now
                print(f"[Engagement-{call_sid}]: 🔔 Speech started at: {speech_start_ref[0]}")

            time_speaking = now - speech_start_ref[0]
            last_disengaged_time = 0

            print(f"[Engagement-{call_sid}]: ⏱️ User has been speaking for {time_speaking:.2f}s")

            if (
                (
                    last_engaged_time == 0 and time_speaking >= ENGAGEMENT_TRIGGER_SECONDS
                )
                or (
                    last_engaged_time > 0 and (now - last_engaged_time) >= ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY
                )
            ) and not tts_active and not barge_in_detected_ref[0]:

                print(f"[Engagement-{call_sid}]: 📣 Sending engagement response")

                text = get_engagement_response("ENGAGED", "hi")
                print(f"[Engagement-{call_sid}]: 🗨️ Response: '{text}'")

                engagement_tts_stop_event_ref.clear()
                text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()

                engagement_tts_task_ref[0] = asyncio.create_task(
                    stream_cached_or_generate_prompt(
                        websocket=websocket,
                        stream_sid=stream_sid,
                        call_sid=call_sid,
                        stop_event=engagement_tts_stop_event_ref,
                        greeting_text=text,
                        engagement_mark_name_ref=engagement_mark_name_ref,
                        response_mark_name_ref=response_mark_name_ref,
                        cache_subdir=f"engaged_response/{text_hash}.ulaw",
                        mark_name="engagement_response",
                        mark_type="engagement",
                    )
                )

                last_engaged_time = now

        elif (engagement_mark_name_ref[0] and not engagement_mark_name_ref[0].endswith("tts_complete")) or (response_mark_name_ref[0] and not response_mark_name_ref[0].endswith("tts_complete")):
            print(f"[Engagement-{call_sid}]: 💤 TTS still playing, ignoring silence")
            silent_since = None
            last_disengaged_time = now

        else:
            if silent_since is None:
                silent_since = now
                speech_start_ref[0] = 0
                print(f"[Engagement-{call_sid}]: 🔕 Silence started at {silent_since}")

            time_silent = now - silent_since
            last_engaged_time = 0

            print(f"[Engagement-{call_sid}]: ⏱️ User silent for {time_silent:.2f}s")

            if (
                (
                    last_disengaged_time == 0 and time_silent >= DISENGAGEMENT_TRIGGER_SECONDS
                )
                or (
                    last_disengaged_time > 0 and (now - last_disengaged_time) >= DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY
                )
            ) and not tts_active and not barge_in_detected_ref[0]:

                print(f"[Engagement-{call_sid}]: 😴 Sending disengagement response")

                text = get_engagement_response("DISENGAGED", "hi")
                print(f"[Engagement-{call_sid}]: 🗨️ Response: '{text}'")

                engagement_tts_stop_event_ref.clear()
                
                text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()

                engagement_tts_task_ref[0] = asyncio.create_task(
                    stream_cached_or_generate_prompt(
                        websocket=websocket,
                        stream_sid=stream_sid,
                        call_sid=call_sid,
                        stop_event=engagement_tts_stop_event_ref,
                        greeting_text=text,
                        engagement_mark_name_ref=engagement_mark_name_ref,
                        response_mark_name_ref=response_mark_name_ref,
                        cache_subdir=f"disengaged_response/{text_hash}.ulaw",
                        mark_name="disengagement_response",
                        mark_type="engagement",
                    )
                )

                last_disengaged_time = now
                print(f"[Engagement-{call_sid}]: ⏰ Last disengaged time updated to {last_disengaged_time}")    


# Detect silence and barge-in during user response
async def detect_silence_and_respond(
    websocket,
    stream_sid,
    call_sid,
    raw_buffer_ref,
    stop_event,
    last_audio_time_ref,
    response_tts_task_ref,
    response_tts_stop_event_ref,
    engagement_tts_task_ref,
    engagement_tts_stop_event_ref,
    speech_start_ref,
    engagement_mark_name_ref,
    response_mark_name_ref,
    barge_in_detected_ref,
):
    print(f"[Silence-{call_sid}]: Starting silence and barge-in monitor")

    while not stop_event.is_set():
        await asyncio.sleep(0.25)
        now = asyncio.get_event_loop().time()
        elapsed = now - last_audio_time_ref[0]

        buffer = raw_buffer_ref[0]

        # 🔍 Silence Detection First (shared across conditions)
        frames = [buffer[i:i + VAD_FRAME_SIZE] for i in range(0, len(buffer), VAD_FRAME_SIZE)]
        silent_frames = sum(
            1 for frame in frames[-5:] if len(frame) == VAD_FRAME_SIZE and not is_voiced(frame)
        )

        if len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES:

            if(engagement_tts_task_ref[0] and not engagement_tts_task_ref[0].done()):
                print(f"[Barge-in-{call_sid}]: Engagement TTS is active")
                # If engagement response is active, wait for it to finish
                if engagement_mark_name_ref[0] == "engagement_response":
                    print(
                        f"[Barge-in-{call_sid}]: Engagement response TTS waiting to complete it."
                    )
                    await wait_for_tts_finish(engagement_tts_task_ref[0])
                else:
                    engagement_tts_stop_event_ref.set()
                    websocket.send(
                        json.dumps({"event": "clear", "streamSid": stream_sid})
                    )


            print(f"[Barge-in-{call_sid}]: Elapsed time since last audio: {elapsed:.2f}s, raw_buffer_ref -: {len(raw_buffer_ref[0])} bytes,\n tts_task_ref -: {response_mark_name_ref[0]}, tts_task_ref[0].done():--{not response_tts_task_ref[0].done() if response_tts_task_ref[0] else ""} response_mark_name_ref:-- {response_mark_name_ref[0]}, \nsilent_frames >= 5 == {silent_frames >= 5}")
            
            if ( response_tts_task_ref[0] and not response_tts_task_ref[0].done()) or (response_mark_name_ref[0] and not response_mark_name_ref[0].endswith("tts_complete")):
                barge_in_detected_ref[0] = True
                # ⏱ Start timing
                start_time = asyncio.get_event_loop().time()

                print(
                    f"[Barge-in-{call_sid}]: User is talking while TTS is active, checking engagement..."
                )
                audio_file = convert_mulaw_to_wav(call_sid, raw_buffer_ref[0])

                # buffer_ref[0],
                whisper_result = transcribe_audio_whisper_groq(audio_file, "hi")
                # os.remove(audio_file)

                user_text = (
                    whisper_result
                    if isinstance(whisper_result, str)
                    else whisper_result.get("text")
                )

                if not user_text:
                    raw_buffer_ref[0] = b""
                    speech_start_ref[0] = 0
                    barge_in_detected_ref[0] = False
                    continue

                is_engagement = await is_user_engagement(
                    user_text=user_text, call_sid=call_sid, lang="hi"
                )

                # ⏱ End timing
                end_time = asyncio.get_event_loop().time()

                print(
                    f"[Barge-in-{call_sid}]: Engagement check took {end_time - start_time:.2f} seconds, check result: {is_engagement}"
                )

                if is_engagement:
                    print(
                        f"[Barge-in-{call_sid}]: Engagement detected, continuing TTS."
                    )
                    raw_buffer_ref[0] = b""
                    speech_start_ref[0] = 0
                    barge_in_detected_ref[0] = False

                    continue  # Do nothing — let TTS stream finish
                else:
                    print(f"[Barge-in-{call_sid}]: User interrupted AI TTS")

                    await websocket.send(
                        json.dumps({"event": "clear", "streamSid": stream_sid})
                    )

                    barge_in_detected_ref[0] = False
                    speech_start_ref[0] = 0
                    raw_buffer_ref[0] = b""
                    speech_start_ref[0] = 0
                    response_tts_stop_event_ref.set()
                    engagement_tts_stop_event_ref.set()

                    await websocket.send(
                        json.dumps(
                            {
                                "event": "mark",
                                "streamSid": stream_sid,
                                "mark": {"name": "interrupt_tts_complete"},
                            }
                        )
                    )

            # Detect end of user speech by checking silence duration
            elif silent_frames >= VAD_MIN_SILENCE_FRAMES or elapsed > AUDIO_BUFFER_SILENCE:
                print(f"-----------------transcribing...")
                try:
                    barge_in_detected_ref[0] = False  # Reset barge-in state

                    response_mark_name_ref[0] = "ai_response"
                    audio_file = convert_mulaw_to_wav(call_sid, raw_buffer_ref[0])

                    raw_buffer_ref[0] = b""
                    speech_start_ref[0] = 0

                    whisper_result = transcribe_audio_whisper_groq(audio_file, "hi")
                    os.remove(audio_file)

                    user_text = (
                        whisper_result
                        if isinstance(whisper_result, str)
                        else whisper_result.get("text")
                    )
                    if not user_text:
                        continue

                    print(f"[User-{call_sid}]: {user_text}")

                    await handle_user_transcription(
                        websocket=websocket,
                        stream_sid=stream_sid,
                        call_sid=call_sid,
                        response_tts_task_ref=response_tts_task_ref,
                        response_tts_stop_event_ref=response_tts_stop_event_ref,
                        response_mark_name_ref=response_mark_name_ref,
                        user_text=user_text,
                    )

                except Exception as e:
                    speech_start_ref[0] = 0
                    response_mark_name_ref[0] = None
                    engagement_mark_name_ref[0] = None
                    print(f"[Silence-{call_sid}]: Error during processing: {e}")


async def handle_user_transcription(
    websocket,
    stream_sid,
    call_sid,
    response_tts_task_ref,
    response_tts_stop_event_ref,
    response_mark_name_ref: list,
    user_text: str,
):
    print(f"-----------------handling transcription...")

    try:
        response_mark_name_ref[0] = "ai_response"

        context = get_context(call_sid)
        ai_response = await get_ai_response(user_text, context, call_sid)
        store_context(call_sid, user_text, ai_response)

        # Wait if there's still a running TTS
        if response_tts_task_ref[0] and not response_tts_task_ref[0].done():
            print(f"[AI-TTS-{call_sid}]: Waiting for previous TTS to finish")
            await wait_for_tts_finish(response_tts_task_ref[0])

        response_tts_stop_event_ref.clear()
        
        response_tts_task_ref[0] = asyncio.create_task(
            stream_tts_to_client(
                websocket,
                stream_sid,
                ai_response,
                call_sid,
                response_tts_stop_event_ref,
                mark_name="ai_response",
                mark_type="response",
            )
        )

        await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))

    except Exception as e:
        twilio_mark_name_ref = [None]
        print(f"[Silence-{call_sid}]: Error during processing: {e}")


# Play cached/generated prompt (initial greeting, disengagement, etc.)
async def stream_cached_or_generate_prompt(
    websocket,
    stream_sid,
    call_sid,
    stop_event,
    greeting_text: str,
    engagement_mark_name_ref: list,
    response_mark_name_ref: list,
    cache_subdir: str,
    mark_name: Optional[str] = None,
    mark_type: Optional[str] = "response",
):
    """
    Stream pre-generated or freshly-generated initial greeting.
    Saves and reuses mulaw audio from local disk cache.
    """

    print(f"[TTS-{call_sid}]: Streaming cached or generated prompt: {greeting_text}")

    Path(AUDIO_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    audio_path = Path(AUDIO_CACHE_DIR) / cache_subdir

    # ✅ Ensure full path exists
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    if not cache_subdir.endswith(".ulaw"):
        cache_subdir += ".ulaw"

    if mark_name:
        # Use the provided mark name for TTS completion
        if mark_type == "engagement":
            engagement_mark_name_ref[0] = mark_name
        elif mark_type == "response":
            response_mark_name_ref[0] = mark_name

    # If audio already exists, read it from disk
    if audio_path.exists():
        print(f"[TTS-{call_sid}]: Found cached audio: {audio_path}")
        with open(audio_path, "rb") as f:
            audio_buffer = f.read()
    else:
        print(f"[TTS-{call_sid}]: No cached greeting found, generating TTS...")
        audio_buffer = await generate_mulaw_audio_buffer(greeting_text)

        if not audio_buffer:
            print(f"[TTS-{call_sid}]: Failed to generate TTS greeting.")
            return

        # Save buffer to disk
        with open(audio_path, "wb") as f:
            f.write(audio_buffer)
        print(f"[TTS-{call_sid}]: Cached greeting audio saved at {audio_path}")

    # Play it
    await play_audio_buffer_to_twilio(
        websocket, stream_sid, audio_buffer, stop_event, mark_name=mark_name, mark_type=mark_type
    )


# --- WebSocket Handler ---
async def websocket_handler(websocket):
    print("[+] Client connected to WebSocket")

    # State references
    call_sid, stream_sid = None, None
    raw_buffer_ref = [b""]
    stop_event = asyncio.Event()
    last_audio_time_ref = [asyncio.get_event_loop().time()]
    speech_start_ref = [0]
    engagement_tts_task_ref = [None]
    engagement_tts_stop_event_ref = asyncio.Event()
    response_tts_task_ref:list = [None]
    response_tts_stop_event_ref = asyncio.Event()
    engagement_mark_name_ref = [None]
    response_mark_name_ref = [None]
    barge_in_detected_ref = [False]

    silence_task, engagement_task = None, None

    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                print(f"[Start]: callSid={call_sid}, streamSid={stream_sid}")

                # 🚀 Use a hardcoded fast greeting to save LLM time
                response_tts_task_ref[0] = asyncio.create_task(
                    stream_cached_or_generate_prompt(
                        websocket,
                        stream_sid,
                        call_sid,
                        stop_event=response_tts_stop_event_ref,
                        greeting_text=INITIAL_GREETING_TEXT,
                        engagement_mark_name_ref=engagement_mark_name_ref,
                        response_mark_name_ref=response_mark_name_ref,
                        cache_subdir="initial_greet_response.ulaw",
                        mark_name="initial_greet_response",
                        mark_type="response",
                    )
                )

                store_context(call_sid, "Hello", INITIAL_GREETING_TEXT)

                # Launch silence and engagement detection tasks
                silence_task = asyncio.create_task(
                    detect_silence_and_respond(
                        websocket,
                        stream_sid,
                        call_sid,
                        raw_buffer_ref,
                        stop_event,
                        last_audio_time_ref,
                        response_tts_task_ref,
                        response_tts_stop_event_ref,
                        engagement_tts_task_ref,
                        engagement_tts_stop_event_ref,
                        speech_start_ref,
                        engagement_mark_name_ref,
                        response_mark_name_ref,
                        barge_in_detected_ref,
                    )
                )

                engagement_task = asyncio.create_task(
                    monitor_user_engagement(
                        websocket,
                        stream_sid,
                        call_sid,
                        stop_event,
                        raw_buffer_ref,
                        engagement_tts_task_ref,
                        engagement_tts_stop_event_ref,
                        response_tts_task_ref,
                        response_tts_stop_event_ref,
                        speech_start_ref,
                        engagement_mark_name_ref,
                        response_mark_name_ref,
                        barge_in_detected_ref,
                    )
                )

            elif event == "media":
                if not call_sid:
                    continue

                audio_chunk = base64.b64decode(data["media"]["payload"])
                # buffer_ref[0] += audio_chunk

                now = asyncio.get_event_loop().time()

                is_speech = not is_silent_mulaw_audio(audio_chunk)
                # print(
                #     f"[Media-{call_sid}]: Received audio chunk, is_mulaw_speech={is_mulaw_speech}, size={len(audio_chunk)} bytes"
                # )

                # # ✅ Use VAD instead of energy-based detection
                # is_speech = is_voiced(audio_chunk)
                # print(
                #     f"[Media-{call_sid}]: Received audio chunk, is_speech={is_speech}, size={len(audio_chunk)} bytes"
                # )

                # Append valid audio to raw buffer
                if is_speech:
                    raw_buffer_ref[0] += audio_chunk
                    last_audio_time_ref[0] = now

                    if speech_start_ref[0] == 0:
                        speech_start_ref[0] = int(now)
                elif (len(raw_buffer_ref[0]) > 0) and (
                    now - last_audio_time_ref[0]
                ) < SILENCE_MAX_DURATION:
                    print(
                        f"[Media-{call_sid}]: Received silence, but within max duration: {now - last_audio_time_ref[0]:.2f}s"
                    )
                    raw_buffer_ref[0] += audio_chunk

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name")
                print(f"[Mark-{call_sid}]: Received mark: {mark_name}, data: {data}")
                if mark_name:
                    barge_in_detected_ref[0] = False
                    print(
                        f"[Mark-{call_sid}]: Received twilio mark: {mark_name}"
                    )
                    if mark_name.startswith("engagement_response") or mark_name.startswith("disengagement_response"):
                        engagement_tts_stop_event_ref.set()
                        engagement_mark_name_ref[0] = mark_name
                    elif mark_name.startswith("ai_response"):
                        response_tts_stop_event_ref.set()
                        response_mark_name_ref[0] = mark_name
                    else:
                        response_mark_name_ref[0] = mark_name
                        engagement_mark_name_ref[0] = mark_name
                        engagement_tts_stop_event_ref.set()
                        response_tts_stop_event_ref.set()

    except Exception as e:
        print(f"[WebSocket-{call_sid}]: Error occurred: {e}")

    finally:
        print(f"[Cleanup-{call_sid}]: Performing cleanup")
        stop_event.set()

        # Gracefully shut down TTS
        if response_tts_task_ref[0] and not response_tts_task_ref[0].done():
            response_tts_stop_event_ref.set()
            await wait_for_tts_finish(response_tts_task_ref[0])

        if engagement_tts_task_ref[0] and not engagement_tts_task_ref[0].done():
            engagement_tts_stop_event_ref.set()
            await wait_for_tts_finish(engagement_tts_task_ref[0])

        if silence_task:
            silence_task.cancel()
            try:
                await silence_task
            except asyncio.CancelledError:
                print(f"[Cleanup-{call_sid}]: Silence task cancelled")

        if engagement_task:
            engagement_task.cancel()
            try:
                await engagement_task
            except asyncio.CancelledError:
                print(f"[Cleanup-{call_sid}]: Engagement task cancelled")

        # # Delete cached audio files
        # for filename in os.listdir(AUDIO_CHUNK_DIR):
        #     if f"{call_sid}_" in filename:
        #         try:
        #             os.remove(os.path.join(AUDIO_CHUNK_DIR, filename))
        #         except Exception as e:
        #             print(f"[Cleanup-{call_sid}]: File removal error: {e}")

        try:
            await websocket.send(
                json.dumps({"event": "clear", "streamSid": stream_sid})
            )
            await websocket.close()
        except websockets.exceptions.ConnectionClosedOK:
            print(
                f"[Cleanup-{call_sid or 'Unknown'}]: WebSocket already closed gracefully."
            )
        except Exception as e:
            print(f"[Cleanup-{call_sid or 'Unknown'}]: WebSocket close error: {e}")


# --- Start Server ---


async def main():
    print("WebSocket server is running on port 8765...")
    async with websockets.serve(websocket_handler, "0.0.0.0", 8765):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
