import asyncio
import os
import websockets
import json
import base64
from utils.redis_utils import get_context, store_context
from utils.sarvam_utils import synthesize_mulaw_sarvam_tts, synthesize_streaming_sarvam_tts
from utils.audio_utils import is_silent_mulaw_audio, convert_mulaw_to_wav
from utils.open_ai_utils import get_ai_response, transcribe_audio_whisper_groq
from utils.langchain_agent import LangChainAIAgent

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


async def stream_tts_to_client(websocket, stream_sid, text, call_sid, stop_event, mark_name=None):
    print(f"[TTS-{call_sid}]: Generating TTS for: {text}")
    try:
        # Get μ-law encoded audio bytes
        audio_chunk = await synthesize_mulaw_sarvam_tts(text)
    except Exception as e:
        print(f"[TTS-{call_sid}]: TTS synthesis error: {e}")
        return

    if not audio_chunk:
        print(f"[TTS-{call_sid}]: No audio received from TTS service")
        return

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

        await asyncio.sleep(0.01)  # ~10ms sleep to simulate real-time

    if not stop_event.is_set():
        await websocket.send(json.dumps({
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": f"{mark_name}_tts_complete" if mark_name else "tts_complete"},
        }))


async def stream_real_time_tts_to_client(websocket, stream_sid, text, call_sid, stop_event, mark_name=None):
    """Stream TTS audio using Sarvam AI's streaming API for real-time playback"""
    print(f"[Streaming-TTS-{call_sid}]: Starting real-time TTS for: {text}")
    
    audio_generated = False
    
    try:
        # Use streaming TTS generator
        async for audio_chunk in synthesize_streaming_sarvam_tts(text):
            if stop_event.is_set():
                print(f"[Streaming-TTS-{call_sid}]: Playback interrupted by user")
                break
                
            if not audio_chunk:
                continue
                
            audio_generated = True
            print(f"[Streaming-TTS-{call_sid}]: Received audio chunk of {len(audio_chunk)} bytes")
                
            # Send audio chunk immediately as it arrives
            for i in range(0, len(audio_chunk), AUDIO_CHUNK_SIZE):
                if stop_event.is_set():
                    print(f"[Streaming-TTS-{call_sid}]: Playback interrupted during chunk")
                    break
                    
                chunk = audio_chunk[i: i + AUDIO_CHUNK_SIZE]
                try:
                    await websocket.send(json.dumps({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": base64.b64encode(chunk).decode()},
                    }))
                except websockets.exceptions.ConnectionClosed:
                    print(f"[Streaming-TTS-{call_sid}]: WebSocket connection closed during playback")
                    return
                    
                await asyncio.sleep(0.01)  # ~10ms sleep to simulate real-time
                
    except Exception as e:
        print(f"[Streaming-TTS-{call_sid}]: Error in streaming TTS: {e}")
        
    # Fallback to regular TTS if no audio was generated
    if not audio_generated:
        print(f"[Streaming-TTS-{call_sid}]: No audio generated, falling back to regular TTS")
        try:
            # Get μ-law encoded audio bytes using regular TTS
            audio_chunk = await synthesize_mulaw_sarvam_tts(text)
            if audio_chunk:
                for i in range(0, len(audio_chunk), AUDIO_CHUNK_SIZE):
                    if stop_event.is_set():
                        print(f"[Fallback-TTS-{call_sid}]: Playback interrupted by user")
                        break

                    chunk = audio_chunk[i: i + AUDIO_CHUNK_SIZE]
                    try:
                        await websocket.send(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(chunk).decode()},
                        }))
                    except websockets.exceptions.ConnectionClosed:
                        print(f"[Fallback-TTS-{call_sid}]: WebSocket connection closed during playback")
                        return

                    await asyncio.sleep(0.01)  # ~10ms sleep to simulate real-time
                audio_generated = True
        except Exception as fallback_e:
            print(f"[Fallback-TTS-{call_sid}]: Fallback TTS also failed: {fallback_e}")
        
    if not stop_event.is_set() and audio_generated:
        await websocket.send(json.dumps({
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": f"{mark_name}_tts_complete" if mark_name else "streaming_tts_complete"},
        }))
        print(f"[Streaming-TTS-{call_sid}]: Streaming TTS completed")


async def handle_streaming_ai_response(websocket, stream_sid, call_sid, user_text, context, stop_event, tts_task_ref, tts_type_ref, tts_stop_event_ref):
    """Handle AI response with streaming agent and streaming TTS"""
    print(f"[Streaming-AI-{call_sid}]: Processing streaming AI response for: {user_text}")
    
    try:
        # Initialize the LangChain agent
        agent = LangChainAIAgent()
        
        # Collect streaming response chunks
        response_chunks = []
        sentence_buffer = ""
        
        # Stream AI response
        async for chunk in agent.process_query_streaming(user_text, call_sid, context):
            response_chunks.append(chunk)
            sentence_buffer += chunk
            
            # Check if we have a complete sentence or substantial chunk
            if (sentence_buffer.strip().endswith(('.', '!', '?')) or 
                len(sentence_buffer.strip()) > 50):
                
                # Send this chunk to streaming TTS
                if sentence_buffer.strip():
                    print(f"[Streaming-AI-{call_sid}]: Sending chunk to TTS: {sentence_buffer.strip()}")
                    
                    # Wait for any existing TTS to finish
                    if tts_task_ref[0] and not tts_task_ref[0].done():
                        await wait_for_tts_finish(tts_task_ref[0])
                    
                    tts_stop_event_ref.clear()
                    tts_type_ref[0] = "streaming_ai_response"
                    tts_task_ref[0] = asyncio.create_task(
                        stream_real_time_tts_to_client(websocket, stream_sid, sentence_buffer.strip(), 
                                                     call_sid, tts_stop_event_ref, mark_name="streaming_ai_chunk")
                    )
                    
                    sentence_buffer = ""
                    
                    # Small delay to allow audio to start playing
                    await asyncio.sleep(0.1)
        
        # Handle any remaining content
        if sentence_buffer.strip():
            print(f"[Streaming-AI-{call_sid}]: Sending final chunk to TTS: {sentence_buffer.strip()}")
            
            # Wait for any existing TTS to finish
            if tts_task_ref[0] and not tts_task_ref[0].done():
                await wait_for_tts_finish(tts_task_ref[0])
            
            tts_stop_event_ref.clear()
            tts_type_ref[0] = "streaming_ai_response"
            tts_task_ref[0] = asyncio.create_task(
                stream_real_time_tts_to_client(websocket, stream_sid, sentence_buffer.strip(), 
                                             call_sid, tts_stop_event_ref, mark_name="streaming_ai_final")
            )
        
        # Store the complete response in context
        full_response = "".join(response_chunks)
        store_context(call_sid, user_text, full_response)
        
        return full_response
        
    except Exception as e:
        print(f"[Streaming-AI-{call_sid}]: Error in streaming AI response: {e}")
        # Fallback to regular AI response
        ai_response = await get_ai_response(user_text, context, call_sid)
        store_context(call_sid, user_text, ai_response)
        return ai_response


# Ensure TTS task finishes gracefully
async def wait_for_tts_finish(tts_task):
    try:
        await asyncio.shield(tts_task)
    except Exception as e:
        print(f"[TTS Cleanup Error]: {e}")


async def monitor_user_engagement(websocket, stream_sid, call_sid, stop_event, raw_buffer_ref, tts_task_ref, tts_type_ref, tts_stop_event_ref, speech_start_ref):
    print(f"[Engagement-{call_sid}]: Starting user engagement monitor")

    last_engaged_time = 0
    last_disengaged_time = 0
    silent_since = None

    while not stop_event.is_set():
        await asyncio.sleep(0.50)
        now = asyncio.get_event_loop().time()

        user_is_talking = len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES
        tts_active = tts_task_ref[0] and not tts_task_ref[0].done()

        if not tts_task_ref[0] or tts_task_ref[0].done():
            tts_type_ref[0] = None   # Reset the TTS type to None, indicating that no TTS is currently being played
        
        if user_is_talking:
            if silent_since is not None:
                print(f"[Engagement-{call_sid}]: User started speaking again")
            silent_since = None

            if speech_start_ref[0] == 0:
                speech_start_ref[0] = now

            time_speaking = now - speech_start_ref[0]
            last_disengaged_time = 0  # reset disengaged time when talking
            # print(f"--time_speaking--: {time_speaking}, user_is_talking---: {user_is_talking}, last_engaged_time--: {last_engaged_time}, now - last_engaged_time--: {now - last_engaged_time}")

            if (
                (last_engaged_time == 0 and time_speaking >= ENGAGEMENT_TRIGGER_SECONDS) or
                (last_engaged_time > 0 and (now - last_engaged_time) >= ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY)
            ) and not tts_active:

                # text = get_engagement_response("ENGAGED", "hi")
                # print(f"[Engagement-{call_sid}]: Sending engaged response: '{text}'")

                # tts_stop_event_ref.clear()
                # tts_type_ref[0] = "engagement_response"
                # tts_task_ref[0] = asyncio.create_task(
                #     stream_tts_to_client(websocket, stream_sid, text, call_sid, tts_stop_event_ref, mark_name="engagement_response")
                # )
                last_engaged_time = now
        elif not tts_type_ref[0] == "ai_response":
            if silent_since is None:
                silent_since = now
                speech_start_ref[0] = 0  # Reset speech start when silence begins

            time_silent = now - silent_since
            last_engaged_time = 0  # reset engaged time when silent
            # print(f"silent_since--: {silent_since}, time_silent--: {time_silent}, DISENGAGEMENT_TRIGGER_SECONDS---: {DISENGAGEMENT_TRIGGER_SECONDS}, last_disengaged_time--: {last_disengaged_time}, now - last_disengaged_time--: {now - last_disengaged_time}")

            if (
                (last_disengaged_time == 0 and time_silent >= DISENGAGEMENT_TRIGGER_SECONDS) or
                (last_disengaged_time > 0 and (now - last_disengaged_time) >= DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY)
            ) and not tts_active:

                text = get_engagement_response("DISENGAGED", "hi")
                print(f"[Engagement-{call_sid}]: Sending disengaged response: '{text}'")

                tts_stop_event_ref.clear()
                tts_type_ref[0] = "disengagement_response"
                tts_task_ref[0] = asyncio.create_task(
                    stream_real_time_tts_to_client(websocket, stream_sid, text, call_sid, tts_stop_event_ref, mark_name="disengagement_response")
                )
                last_disengaged_time = now


async def detect_silence_and_respond(websocket, stream_sid, call_sid, buffer_ref, raw_buffer_ref, stop_event, last_audio_time_ref, tts_task_ref, tts_type_ref, tts_stop_event_ref, speech_start_ref):
    print(f"[Silence-{call_sid}]: Starting silence and barge-in monitor")

    while not stop_event.is_set():
        await asyncio.sleep(0.25)
        now = asyncio.get_event_loop().time()
        elapsed = now - last_audio_time_ref[0]

        if len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES and tts_task_ref[0] and not tts_task_ref[0].done() and not tts_type_ref[0] == "engagement_response":
            print(f"[Barge-in-{call_sid}]: User interrupted AI TTS")
            tts_stop_event_ref.set()
            await wait_for_tts_finish(tts_task_ref[0])
            await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
            await websocket.send(json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": "tts_interrupted"}}))

        if len(raw_buffer_ref[0]) > MIN_AUDIO_BYTES and elapsed >= AUDIO_BUFFER_SILENCE:
            print(f"[Silence-{call_sid}]: Silence detected after {elapsed:.2f}s, transcribing audio, now - speech_start_ref[0]-- {now - speech_start_ref[0]}")
            try:
                audio_file = convert_mulaw_to_wav(call_sid, raw_buffer_ref[0])
                buffer_ref[0] = b""
                raw_buffer_ref[0] = b""
                speech_start_ref[0] = 0

                whisper_result = transcribe_audio_whisper_groq(audio_file, "hi")

                # Remove temporary audio file after transcription to free up disk space
                if whisper_result:
                    os.remove(audio_file)
                
                user_text = whisper_result if isinstance(whisper_result, str) else whisper_result.get("text")

                if not user_text:
                    continue

                print(f"[User-{call_sid}]: {user_text}")

                if tts_task_ref[0] and not tts_task_ref[0].done() and tts_type_ref[0] == "engagement_reply":
                    print(f"[Silence-{call_sid}]: Interrupting engagement reply TTS")
                    await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
                    await websocket.send(json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": "engagement_reply_tts_interrupted"}}))
                
                context = get_context(call_sid)
                
                # Use streaming AI response with streaming TTS
                ai_response = await handle_streaming_ai_response(
                    websocket, stream_sid, call_sid, user_text, context, 
                    stop_event, tts_task_ref, tts_type_ref, tts_stop_event_ref
                )

                await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))

            except Exception as e:
                print(f"[Silence-{call_sid}]: Error during processing: {e}")


async def websocket_handler(websocket):
    print("[+] Client connected to WebSocket")

    call_sid, stream_sid = None, None
    buffer_ref, raw_buffer_ref = [b""], [b""]
    tts_task_ref = [None]
    tts_type_ref = [None]
    tts_stop_event = asyncio.Event()
    stop_event = asyncio.Event()
    last_audio_time_ref = [asyncio.get_event_loop().time()]
    speech_start_ref = [0]

    silence_task, engagement_task = None, None

    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                print(f"[Start]: callSid={call_sid}, streamSid={stream_sid}")

                silence_task = asyncio.create_task(
                    detect_silence_and_respond(websocket, stream_sid, call_sid, buffer_ref, raw_buffer_ref, stop_event,
                                               last_audio_time_ref, tts_task_ref, tts_type_ref, tts_stop_event, speech_start_ref))

                engagement_task = asyncio.create_task(
                    monitor_user_engagement(websocket, stream_sid, call_sid, stop_event,
                                            raw_buffer_ref, tts_task_ref, tts_type_ref, tts_stop_event, speech_start_ref))

                # Send greeting message immediately after connection
                greeting_message = "Hi Aman, this is Manisha from Omen Tech Innovations! Do you run a business or work with one that handles customer calls?"
                print(f"[Greeting-{call_sid}]: Sending greeting message")
                
                tts_stop_event.clear()
                tts_type_ref[0] = "greeting"
                tts_task_ref[0] = asyncio.create_task(
                    stream_real_time_tts_to_client(websocket, stream_sid, greeting_message, call_sid, tts_stop_event, mark_name="greeting")
                )

            elif event == "media":
                if not call_sid:
                    continue

                audio_chunk = base64.b64decode(data["media"]["payload"])
                buffer_ref[0] += audio_chunk

                now = asyncio.get_event_loop().time()
                is_speech = not is_silent_mulaw_audio(audio_chunk)

                if is_speech:
                    raw_buffer_ref[0] += audio_chunk
                    last_audio_time_ref[0] = now

                    if speech_start_ref[0] == 0:
                        speech_start_ref[0] = int(now)
                elif (now - last_audio_time_ref[0]) < SILENCE_MAX_DURATION:
                    # Allow brief silence  
                    raw_buffer_ref[0] += audio_chunk
                else:
                    # Skip extended silence
                    pass

    except Exception as e:
        print(f"[WebSocket-{call_sid}]: Error occurred: {e}")

    finally:
        print(f"[Cleanup-{call_sid}]: Performing cleanup")
        stop_event.set()

        if tts_task_ref[0] and not tts_task_ref[0].done():
            tts_stop_event.set()
            await wait_for_tts_finish(tts_task_ref[0])

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

        # for filename in os.listdir(AUDIO_CHUNK_DIR):
        #     if f"{call_sid}_" in filename:
        #         try:
        #             os.remove(os.path.join(AUDIO_CHUNK_DIR, filename))
        #         except Exception as e:
        #             print(f"[Cleanup-{call_sid}]: File removal error: {e}")

        try:
            await websocket.send(json.dumps({"event": "clear", "streamSid": stream_sid}))
            await websocket.close()
        except websockets.exceptions.ConnectionClosedOK:
            print(f"[Cleanup-{call_sid or 'Unknown'}]: WebSocket already closed gracefully.")
        except Exception as e:
            print(f"[Cleanup-{call_sid or 'Unknown'}]: WebSocket close error: {e}")


async def main():
    print("WebSocket server is running on port 8765...")
    async with websockets.serve(websocket_handler, "0.0.0.0", 8765):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())