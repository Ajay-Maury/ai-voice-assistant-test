import os
import json
import base64
import logging
import threading
import time
import io
import tempfile
import wave
import struct
import requests
import uuid
from flask import Flask, request, Response, send_file
try:
    from flask_sockets import Sockets
    FLASK_SOCKETS_AVAILABLE = True
except ImportError:
    FLASK_SOCKETS_AVAILABLE = False
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Connect, Stream, Play
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('voice_assistant.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize sockets only if flask-sockets is available
if FLASK_SOCKETS_AVAILABLE:
    sockets = Sockets(app)
else:
    sockets = None

# Safe logging helper function
def safe_log(level, message, *args, **kwargs):
    """Safe logging that won't crash the app"""
    try:
        # Sanitize the message and arguments
        safe_message = str(message) if message is not None else "None"
        safe_args = [str(arg) if arg is not None else "None" for arg in args]
        
        # Remove or replace problematic characters
        safe_message = safe_message.encode('ascii', errors='ignore').decode('ascii')
        safe_args = [arg.encode('ascii', errors='ignore').decode('ascii') for arg in safe_args]
        
        if level == 'info':
            logger.info(safe_message, *safe_args, **kwargs)
        elif level == 'error':
            logger.error(safe_message, *safe_args, **kwargs)
        elif level == 'warning':
            logger.warning(safe_message, *safe_args, **kwargs)
        elif level == 'debug':
            logger.debug(safe_message, *safe_args, **kwargs)
    except Exception as e:
        # Fallback logging if safe_log itself fails
        try:
            logger.error(f"Logging error: {str(e)}")
        except:
            print(f"Critical logging failure: {str(e)}")

# Environment variables with validation
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://3661-115-99-250-180.ngrok-free.app")

# Validate required environment variables
required_vars = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"]
for var in required_vars:
    if not os.getenv(var):
        raise ValueError(f"Missing required environment variable: {var}")

# ElevenLabs configuration
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default voice (Rachel)
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_monolingual_v1")
USE_ELEVENLABS = os.getenv("USE_ELEVENLABS", "false").lower() == "true"

# Audio storage for generated files
AUDIO_STORAGE = {}

# OpenAI config with fallback support
if os.getenv("OPENAI_API_KEY"):
    open_ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    print("OpenAi")
elif all([os.getenv("AZURE_OPENAI_API_KEY"), os.getenv("AZURE_OPENAI_ENDPOINT")]):
    print("Azure open ai")
    open_ai_client = OpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        base_url=f"{os.getenv('AZURE_OPENAI_ENDPOINT')}/openai/deployments/{os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME')}",
        default_headers={"api-version": os.getenv("AZURE_OPENAI_VERSION", "2023-05-15")}
    )
else:
    raise ValueError("Missing OpenAI configuration. Provide either OPENAI_API_KEY or Azure OpenAI credentials.")

WHISPER_MODEL = "whisper-1"
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Thread-safe map for WebSocket control and audio buffers
STREAM_STATE = {}

# --- ElevenLabs TTS Functions ---
def generate_elevenlabs_audio(text: str) -> str:
    """Generate audio using ElevenLabs API and return file path"""
    try:
        safe_log('info', f"Attempting ElevenLabs TTS for text: {text[:50]}...")
        
        if not ELEVENLABS_API_KEY:
            safe_log('error', "ElevenLabs API key not configured")
            return None
        
        if not ELEVENLABS_VOICE_ID:
            safe_log('error', "ElevenLabs voice ID not configured")
            return None
            
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        safe_log('info', f"ElevenLabs URL: {url}")
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        data = {
            "text": text,
            "model_id": ELEVENLABS_MODEL_ID,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5,
                "style": 0.0,
                "use_speaker_boost": True
            }
        }
        
        safe_log('info', f"Making ElevenLabs API request with model: {ELEVENLABS_MODEL_ID}")
        response = requests.post(url, json=data, headers=headers, timeout=30)
        
        safe_log('info', f"ElevenLabs API response status: {response.status_code}")
        
        if response.status_code == 200:
            # Generate unique filename
            audio_id = str(uuid.uuid4())
            filename = f"elevenlabs_{audio_id}.mp3"
            filepath = os.path.join(tempfile.gettempdir(), filename)
            
            # Save audio file
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            # Store in memory for cleanup
            AUDIO_STORAGE[audio_id] = filepath
            
            safe_log('info', f"Successfully generated ElevenLabs audio: {filename}, size: {len(response.content)} bytes")
            return audio_id
        else:
            safe_log('error', f"ElevenLabs API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        safe_log('error', f"ElevenLabs generation error: {str(e)}")
        return None

@app.route('/audio/<audio_id>')
def serve_audio(audio_id):
    """Serve generated audio files"""
    try:
        if audio_id in AUDIO_STORAGE:
            filepath = AUDIO_STORAGE[audio_id]
            if os.path.exists(filepath):
                def cleanup_after_send():
                    # Clean up after serving
                    try:
                        os.unlink(filepath)
                        AUDIO_STORAGE.pop(audio_id, None)
                    except:
                        pass
                
                # Schedule cleanup after response
                threading.Timer(5.0, cleanup_after_send).start()
                
                return send_file(filepath, mimetype='audio/mpeg')
        
        return "Audio not found", 404
    except Exception as e:
        safe_log('error', f"Audio serving error: {str(e)}")
        return "Error serving audio", 500

# Test endpoint for ElevenLabs
@app.route('/test-elevenlabs', methods=['GET', 'POST'])
def test_elevenlabs():
    """Test ElevenLabs API integration"""
    try:
        test_text = request.args.get('text', 'Hello, this is a test of ElevenLabs voice synthesis.')
        
        # Log configuration
        safe_log('info', f"Testing ElevenLabs with:")
        safe_log('info', f"API Key configured: {bool(ELEVENLABS_API_KEY)}")
        safe_log('info', f"Voice ID: {ELEVENLABS_VOICE_ID}")
        safe_log('info', f"Model ID: {ELEVENLABS_MODEL_ID}")
        safe_log('info', f"USE_ELEVENLABS: {USE_ELEVENLABS}")
        
        if not USE_ELEVENLABS:
            return {"error": "ElevenLabs is disabled. Set USE_ELEVENLABS=true in .env"}, 400
        
        if not ELEVENLABS_API_KEY:
            return {"error": "ELEVENLABS_API_KEY not configured in .env"}, 400
        
        audio_id = generate_elevenlabs_audio(test_text)
        
        if audio_id:
            audio_url = f"{PUBLIC_URL}/audio/{audio_id}"
            return {
                "success": True,
                "audio_id": audio_id,
                "audio_url": audio_url,
                "text": test_text,
                "message": "ElevenLabs audio generated successfully"
            }
        else:
            return {"error": "Failed to generate audio with ElevenLabs"}, 500
            
    except Exception as e:
        safe_log('error', f"ElevenLabs test error: {str(e)}")
        return {"error": f"Test failed: {str(e)}"}, 500

# --- Helper: generate TwiML with barge-in gather ---
def twiml_with_reply(ai_reply: str, enable_stream: bool = False) -> str:
    vr = VoiceResponse()
    
    # 1) Start media stream (only if flask-sockets is working properly)
    if enable_stream and FLASK_SOCKETS_AVAILABLE and sockets:
        try:
            connect = Connect()
            # Extract host from PUBLIC_URL or use request.host
            stream_host = PUBLIC_URL.replace('https://', '').replace('http://', '') if PUBLIC_URL else request.host
            connect.append(Stream(url=f"wss://{stream_host}/stream"))
            vr.append(connect)
            safe_log('info', f"Added WebSocket stream to TwiML: wss://{stream_host}/stream")
        except Exception as e:
            safe_log('error', f"Failed to add WebSocket stream: {str(e)}")

    # 2) Barge-in gather with voice selection
    gather = Gather(
        input="speech",
        bargeIn=True,
        action=f"{PUBLIC_URL}/ai-response",
        method="POST",
        speechTimeout="auto",
        profanityFilter="false",
        speechModel="phone_call"
    )
    
    # Use ElevenLabs or Polly based on configuration
    if USE_ELEVENLABS and ELEVENLABS_API_KEY:
        audio_id = generate_elevenlabs_audio(ai_reply)
        if audio_id:
            gather.play(f"{PUBLIC_URL}/audio/{audio_id}")
        else:
            # Fallback to Polly if ElevenLabs fails
            gather.say(ai_reply, voice="Polly.Kajal-Generative")
    else:
        gather.say(ai_reply, voice="Polly.Kajal-Generative")
    
    vr.append(gather)
    
    # Fallback if no speech detected
    fallback_text = "I didn't hear anything. Please try again."
    if USE_ELEVENLABS and ELEVENLABS_API_KEY:
        fallback_audio_id = generate_elevenlabs_audio(fallback_text)
        if fallback_audio_id:
            vr.play(f"{PUBLIC_URL}/audio/{fallback_audio_id}")
        else:
            vr.say(fallback_text, voice="Polly.Kajal-Generative")
    else:
        vr.say(fallback_text, voice="Polly.Kajal-Generative")
    
    vr.redirect(f"{PUBLIC_URL}/voice")
    
    return str(vr)

# --- Webhook: incoming call ---
@app.route("/voice", methods=["POST"])
def voice():
    return Response(
        twiml_with_reply("Hello, I am your AI assistant. How can I help you today?"),
        mimetype="text/xml"
    )

# --- Webhook: AI response ---
@app.route("/ai-response", methods=["POST"])
def ai_response():
    try:
        user_input = request.form.get("SpeechResult", "").strip()
        safe_log('info', f"AI-response triggered, user said: {user_input}")

        if not user_input:
            return Response(
                twiml_with_reply("I didn't catch that, could you please repeat?"),
                mimetype="text/xml"
            )

        # Exit phrases
        if any(phrase in user_input.lower() for phrase in ["goodbye", "hang up", "stop", "bye", "end call"]):
            vr = VoiceResponse()
            goodbye_text = "Goodbye! Have a great day!"
            
            if USE_ELEVENLABS and ELEVENLABS_API_KEY:
                goodbye_audio_id = generate_elevenlabs_audio(goodbye_text)
                if goodbye_audio_id:
                    vr.play(f"{PUBLIC_URL}/audio/{goodbye_audio_id}")
                else:
                    vr.say(goodbye_text, voice="Polly.Kajal-Generative")
            else:
                vr.say(goodbye_text, voice="Polly.Kajal-Generative")
            
            vr.hangup()
            return Response(str(vr), mimetype="text/xml")

        # Get AI reply via OpenAI Chat
        ai_reply = get_ai_reply(user_input)
        if not ai_reply:
            ai_reply = "I'm sorry, I'm having trouble processing that. Could you please try again?"
            
        return Response(twiml_with_reply(ai_reply, enable_stream=False), mimetype="text/xml")
        
    except Exception as e:
        safe_log('error', f"Error in ai_response: {str(e)}")
        # Return a safe fallback response instead of crashing
        vr = VoiceResponse()
        error_text = "I'm sorry, I encountered an error. Please try again."
        
        if USE_ELEVENLABS and ELEVENLABS_API_KEY:
            error_audio_id = generate_elevenlabs_audio(error_text)
            if error_audio_id:
                vr.play(f"{PUBLIC_URL}/audio/{error_audio_id}")
            else:
                vr.say(error_text, voice="Polly.Kajal-Generative")
        else:
            vr.say(error_text, voice="Polly.Kajal-Generative")
        
        vr.redirect(f"{PUBLIC_URL}/voice")
        return Response(str(vr), mimetype="text/xml")

# --- WebSocket: Media Stream ---
# Add error handling for WebSocket routing
@app.errorhandler(Exception)
def handle_websocket_error(e):
    if "WebsocketMismatch" in str(e):
        safe_log('warning', f"WebSocket connection mismatch: {str(e)}")
        return "WebSocket connection not supported", 400
    return str(e), 500

# WebSocket route (only if flask-sockets is available)
if FLASK_SOCKETS_AVAILABLE and sockets:
    @sockets.route('/stream')
    def media_stream(ws):
        sid = None
        buffer = io.BytesIO()
        
        # Initialize stream state with thread-safe access
        stream_key = id(ws)  # Use websocket ID as temporary key
        STREAM_STATE[stream_key] = {
            'ws': ws, 
            'buffer': buffer, 
            'bot_talking': True,
            'last_activity': time.time()
        }
        
        try:
            while not ws.closed:
                msg = ws.receive()
                if not msg:
                    break
                    
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError as e:
                    safe_log('error', f"Invalid JSON received: {str(e)}")
                    continue
                    
                event = data.get('event')
                
                if event == 'start':
                    sid = data.get('streamSid')
                    if sid:
                        # Move state to proper SID key
                        STREAM_STATE[sid] = STREAM_STATE.pop(stream_key, {})
                        STREAM_STATE[sid].update({
                            'ws': ws,
                            'buffer': buffer,
                            'bot_talking': True,
                            'last_activity': time.time()
                        })
                        safe_log('info', f"Stream started with SID: {sid}")
                        
                elif event == 'media' and sid:
                    # Decode base64 payload and append to buffer
                    if sid in STREAM_STATE:
                        payload = data.get('media', {}).get('payload', '')
                        if payload:
                            try:
                                audio_data = base64.b64decode(payload)
                                STREAM_STATE[sid]['buffer'].write(audio_data)
                                STREAM_STATE[sid]['last_activity'] = time.time()
                            except Exception as e:
                                safe_log('error', f"Error processing audio data: {str(e)}")
                                
                elif event == 'stop' and sid:
                    # Process accumulated audio when stream stops
                    if sid in STREAM_STATE:
                        buffer = STREAM_STATE[sid]['buffer']
                        if buffer.tell() > 0:  # Only process if there's audio data
                            transcript = whisper_transcribe(buffer)
                            if transcript:
                                safe_log('info', f"Whisper transcript: {transcript}")
                                # Store transcript for potential use
                                STREAM_STATE[sid]['last_transcript'] = transcript
                            
        except Exception as e:
            safe_log('error', f"WebSocket error: {str(e)}")
        finally:
            # Clean up stream state
            cleanup_keys = [k for k in [stream_key, sid] if k and k in STREAM_STATE]
            for key in cleanup_keys:
                STREAM_STATE.pop(key, None)
            
            if not ws.closed:
                try:
                    ws.close()
                except:
                    pass

else:
    # Fallback: Create a dummy endpoint if WebSocket is not available
    @app.route('/stream', methods=['GET', 'POST'])
    def stream_fallback():
        safe_log('warning', "WebSocket stream requested but flask-sockets not available")
        return "WebSocket streaming not available", 501

# --- Audio format conversion helper ---
def convert_mulaw_to_wav(mulaw_data: bytes) -> bytes:
    """Convert μ-law audio data to WAV format for Whisper"""
    try:
        # Decode μ-law to 16-bit PCM
        pcm_data = []
        for byte in mulaw_data:
            # μ-law to linear PCM conversion
            byte = ~byte
            sign = byte & 0x80
            exponent = (byte >> 4) & 0x07
            mantissa = byte & 0x0F
            
            sample = mantissa << (exponent + 3)
            if exponent > 0:
                sample += (1 << (exponent + 7))
            if sign:
                sample = -sample
            
            pcm_data.append(sample)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(8000)  # 8kHz sample rate
            
            # Pack PCM data as 16-bit signed integers
            wav_data = struct.pack('<' + 'h' * len(pcm_data), *pcm_data)
            wav_file.writeframes(wav_data)
        
        wav_buffer.seek(0)
        return wav_buffer.getvalue()
        
    except Exception as e:
        safe_log('error', f"Audio conversion error: {str(e)}")
        return b''

# --- Whisper transcription helper ---
def whisper_transcribe(audio_buffer: io.BytesIO) -> str:
    try:
        audio_buffer.seek(0)
        raw_audio = audio_buffer.getvalue()
        
        if len(raw_audio) < 1000:  # Skip very short audio clips
            return ""
        
        # Convert μ-law to WAV format
        wav_data = convert_mulaw_to_wav(raw_audio)
        if not wav_data:
            return ""
        
        # Create a temporary WAV file for Whisper
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_file.write(wav_data)
            tmp_file.flush()
            
            # Use transcriptions for speech-to-text
            with open(tmp_file.name, 'rb') as audio_file:
                resp = open_ai_client.audio.transcriptions.create(
                    model=WHISPER_MODEL,
                    file=audio_file,
                    language="en",
                    response_format="text"
                )
            
            # Clean up temporary file
            os.unlink(tmp_file.name)
            
            result = resp if isinstance(resp, str) else getattr(resp, 'text', '')
            return result.strip()
            
    except Exception as e:
        safe_log('error', f"Whisper transcription error: {str(e)}")
        return ""

# --- Outgoing call trigger ---
@app.route("/make-call", methods=["POST"])
def make_call():
    to_number = request.form.get('to')
    if not to_number:
        return {'error': "Missing 'to' number"}, 400
    twiml = twiml_with_reply("Hello, I am your AI assistant. How can I help you today?")
    call = client.calls.create(
        twiml=twiml,
        to=to_number,
        from_=TWILIO_NUMBER,
        record=True
    )
    return {'message': 'Call initiated', 'sid': call.sid}

# --- OpenAI helpers ---
def get_ai_reply(prompt: str) -> str:
    try:
        if not prompt or not prompt.strip():
            return "I didn't catch that. Could you please repeat your question?"

        resp = open_ai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful voice assistant. Keep responses concise and conversational, suitable for voice interaction. Limit responses to 2-3 sentences."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )
        
        response = resp.choices[0].message.content.strip()
        return response if response else "I'm sorry, I couldn't generate a response. Please try again."
        
    except Exception as e:
        safe_log('error', f"OpenAI API error: {str(e)}")
        return "I'm sorry, I'm having trouble connecting to my AI service. Please try again in a moment."

if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    port = int(os.getenv("PORT", 8000))
    pywsgi.WSGIServer(("0.0.0.0", port), app, handler_class=WebSocketHandler).serve_forever()
