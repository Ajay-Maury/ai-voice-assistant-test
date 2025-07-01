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
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://e04f-115-99-250-180.ngrok-free.app")

# Validate required environment variables
required_vars = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"]
for var in required_vars:
    if not os.getenv(var):
        raise ValueError(f"Missing required environment variable: {var}")

# Sarvam AI TTS configuration
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_SPEAKER = os.getenv("SARVAM_SPEAKER", "manisha")  # Default female voice
SARVAM_LANGUAGE = os.getenv("SARVAM_LANGUAGE", "hi-IN")  # Default Hindi
SARVAM_PITCH = float(os.getenv("SARVAM_PITCH", "0.0"))  # Range: -0.75 to 0.75
SARVAM_PACE = float(os.getenv("SARVAM_PACE", "1.0"))   # Range: 0.5 to 2.0
SARVAM_LOUDNESS = float(os.getenv("SARVAM_LOUDNESS", "1.0"))  # Range: 0.3 to 3.0
USE_SARVAM_TTS = os.getenv("USE_SARVAM_TTS", "false").lower() == "true"

# User preference language configuration
USER_LANGUAGE = os.getenv("USER_LANGUAGE", "kn-IN")  # User's preferred language
AI_LANGUAGE = os.getenv("AI_LANGUAGE", "en-IN")  # Language for AI processing (usually English)
USE_TRANSLATION = os.getenv("USE_TRANSLATION", "true").lower() == "true"

# Speech timing configuration
SPEECH_TIMEOUT = os.getenv("SPEECH_TIMEOUT", "2")  # Twilio speech timeout: "auto", "1"-"60"
WEBSOCKET_SPEECH_TIMEOUT = float(os.getenv("WEBSOCKET_SPEECH_TIMEOUT", "2.0"))  # Seconds of silence before processing
WEBSOCKET_BUFFER_DURATION = float(os.getenv("WEBSOCKET_BUFFER_DURATION", "30.0"))  # Max buffer duration in seconds

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

# Call session storage for conversation memory
CALL_SESSIONS = {}

# --- Sarvam AI TTS Functions ---
# Valid speakers based on API error response
VALID_SARVAM_SPEAKERS = [
    'meera', 'pavithra', 'maitreyi', 'arvind', 'amol', 'amartya', 
    'diya', 'neel', 'misha', 'vian', 'arjun', 'maya', 'anushka', 
    'abhilash', 'manisha', 'vidya', 'arya', 'karun', 'hitesh'
]

FEMALE_SPEAKERS = ['meera', 'pavithra', 'maitreyi', 'diya', 'misha', 'maya', 'anushka', 'manisha', 'vidya', 'arya']
MALE_SPEAKERS = ['arvind', 'amol', 'amartya', 'neel', 'vian', 'arjun', 'abhilash', 'karun', 'hitesh']

def detect_speech_activity(audio_data: bytes) -> bool:
    """Simple speech activity detection based on audio amplitude"""
    try:
        # Convert audio data to amplitude values
        if len(audio_data) == 0:
            return False
        
        # Calculate RMS (Root Mean Square) for amplitude
        rms = 0
        for i in range(0, len(audio_data), 2):
            if i + 1 < len(audio_data):
                sample = int.from_bytes(audio_data[i:i+2], byteorder='little', signed=True)
                rms += sample * sample
        
        rms = (rms / (len(audio_data) // 2)) ** 0.5
        
        # Threshold for speech detection (adjust as needed)
        speech_threshold = 500  # Empirical value
        return rms > speech_threshold
        
    except Exception as e:
        safe_log('error', f"Speech detection error: {str(e)}")
        return False

def should_process_speech_buffer(sid: str) -> bool:
    """Determine if we should process the accumulated speech buffer"""
    if sid not in STREAM_STATE:
        return False
    
    state = STREAM_STATE[sid]
    current_time = time.time()
    
    # Check if we have enough silence after speech
    if (state.get('silence_start_time') and 
        current_time - state['silence_start_time'] >= WEBSOCKET_SPEECH_TIMEOUT):
        return True
    
    # Check if buffer is getting too long
    if (state.get('speech_start_time') and 
        current_time - state['speech_start_time'] >= WEBSOCKET_BUFFER_DURATION):
        return True
    
    return False

def validate_sarvam_speaker(speaker: str) -> str:
    """Validate and correct speaker name if needed"""
    if speaker.lower() in VALID_SARVAM_SPEAKERS:
        return speaker.lower()
    
    # Try to find closest match
    speaker_lower = speaker.lower()
    for valid_speaker in VALID_SARVAM_SPEAKERS:
        if speaker_lower in valid_speaker or valid_speaker in speaker_lower:
            safe_log('warning', f"Speaker '{speaker}' corrected to '{valid_speaker}'")
            return valid_speaker
    
    # Default fallback
    safe_log('warning', f"Invalid speaker '{speaker}', using default 'manisha'")
    return 'manisha'

# --- Sarvam AI Translation Functions ---
def translate_text(text: str, source_language: str = "auto", target_language: str = "en-IN") -> str:
    """Translate text using Sarvam AI Translation API"""
    try:
        safe_log('info', f"Translating text from {source_language} to {target_language}: {text[:50]}...")
        
        if not SARVAM_API_KEY:
            safe_log('error', "Sarvam AI API key not configured for translation")
            return text  # Return original text if no API key
            
        url = "https://api.sarvam.ai/translate"
        
        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": SARVAM_API_KEY
        }
        
        data = {
            "input": text,
            "source_language_code": source_language,
            "target_language_code": target_language,
            "output_script": "spoken-form-in-native"
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=30)
        
        safe_log('info', f"Sarvam AI Translation response status: {response.status_code}")
        
        if response.status_code == 200:
            response_data = response.json()
            
            if 'translated_text' in response_data:
                translated_text = response_data['translated_text']
                safe_log('info', f"Translation successful: {translated_text[:50]}...")
                return translated_text
            else:
                safe_log('error', "No translated_text in Sarvam AI translation response")
                return text
        else:
            safe_log('error', f"Sarvam AI Translation API error: {response.status_code} - {response.text}")
            return text  # Return original text on error
            
    except Exception as e:
        safe_log('error', f"Sarvam AI translation error: {str(e)}")
        return text  # Return original text on exception

def translate_user_input_to_english(user_input: str) -> str:
    """Translate user input from their preferred language to English for AI processing"""
    if not USE_TRANSLATION or not user_input.strip():
        return user_input
    
    if USER_LANGUAGE == AI_LANGUAGE:
        return user_input  # No translation needed
    
    return translate_text(user_input, source_language="auto", target_language=AI_LANGUAGE)

def translate_ai_response_to_user_language(ai_response: str) -> str:
    """Translate AI response from English to user's preferred language"""
    if not USE_TRANSLATION or not ai_response.strip():
        return ai_response
    
    if AI_LANGUAGE == USER_LANGUAGE:
        return ai_response  # No translation needed
    
    return translate_text(ai_response, source_language=AI_LANGUAGE, target_language=USER_LANGUAGE)

def generate_sarvam_audio(text: str) -> str:
    """Generate audio using Sarvam AI TTS API and return file path"""
    try:
        safe_log('info', f"Attempting Sarvam AI TTS for text: {text[:50]}...")
        
        if not SARVAM_API_KEY:
            safe_log('error', "Sarvam AI API key not configured")
            return None
            
        url = "https://api.sarvam.ai/text-to-speech"
        safe_log('info', f"Sarvam AI URL: {url}")
        
        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": SARVAM_API_KEY
        }
        
        # Truncate text if too long (max 1500 characters)
        if len(text) > 1500:
            text = text[:1497] + "..."
            safe_log('warning', f"Text truncated to 1500 characters for Sarvam AI")



        # Validate and correct speaker name
        validated_speaker = validate_sarvam_speaker(SARVAM_SPEAKER)
        
        data = {
            "text": text,
            "target_language_code": SARVAM_LANGUAGE,
            "speaker": validated_speaker,
            "pitch": SARVAM_PITCH,
            "pace": SARVAM_PACE,
            "loudness": SARVAM_LOUDNESS
        }
        
        safe_log('info', f"Making Sarvam AI request with speaker: {validated_speaker} (from {SARVAM_SPEAKER}), language: {SARVAM_LANGUAGE}")
        response = requests.post(url, json=data, headers=headers, timeout=30)
        
        safe_log('info', f"Sarvam AI response status: {response.status_code}")
        
        if response.status_code == 200:
            response_data = response.json()
            
            if 'audios' in response_data and len(response_data['audios']) > 0:
                # Decode base64 audio data (Sarvam returns base64 encoded WAV)
                audio_base64 = response_data['audios'][0]
                audio_data = base64.b64decode(audio_base64)
                
                # Generate unique filename
                audio_id = str(uuid.uuid4())
                filename = f"sarvam_{audio_id}.wav"
                filepath = os.path.join(tempfile.gettempdir(), filename)
                
                # Save audio file
                with open(filepath, 'wb') as f:
                    f.write(audio_data)
                
                # Store in memory for cleanup
                AUDIO_STORAGE[audio_id] = filepath
                
                safe_log('info', f"Successfully generated Sarvam AI audio: {filename}, size: {len(audio_data)} bytes")
                return audio_id
            else:
                safe_log('error', "No audio data in Sarvam AI response")
                return None
        else:
            safe_log('error', f"Sarvam AI API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        safe_log('error', f"Sarvam AI generation error: {str(e)}")
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
                
                # Determine mimetype based on file extension
                if filepath.endswith('.wav'):
                    mimetype = 'audio/wav'
                elif filepath.endswith('.mp3'):
                    mimetype = 'audio/mpeg'
                else:
                    mimetype = 'audio/wav'  # Default to WAV for Sarvam AI
                
                return send_file(filepath, mimetype=mimetype)
        
        return "Audio not found", 404
    except Exception as e:
        safe_log('error', f"Audio serving error: {str(e)}")
        return "Error serving audio", 500

# Test endpoint for Sarvam AI
@app.route('/test-sarvam', methods=['GET', 'POST'])
def test_sarvam():
    """Test Sarvam AI TTS integration"""
    try:
        test_text = request.args.get('text', 'Hello, this is a test of Sarvam AI voice synthesis in Kannada. ಇದು ಸರ್ವಮ್ AI ಧ್ವನಿ ಸಂಶ್ಲೇಷಣೆಯ ಪರೀಕ್ಷೆಯಾಗಿದೆ.')
        
        # Log configuration
        safe_log('info', f"Testing Sarvam AI with:")
        safe_log('info', f"API Key configured: {bool(SARVAM_API_KEY)}")
        safe_log('info', f"Speaker: {SARVAM_SPEAKER}")
        safe_log('info', f"Language: {SARVAM_LANGUAGE}")
        safe_log('info', f"USE_SARVAM_TTS: {USE_SARVAM_TTS}")
        
        if not USE_SARVAM_TTS:
            return {"error": "Sarvam AI is disabled. Set USE_SARVAM_TTS=true in .env"}, 400
        
        if not SARVAM_API_KEY:
            return {"error": "SARVAM_API_KEY not configured in .env"}, 400
        
        audio_id = generate_sarvam_audio(test_text)
        
        if audio_id:
            audio_url = f"{PUBLIC_URL}/audio/{audio_id}"
            return {
                "success": True,
                "audio_id": audio_id,
                "audio_url": audio_url,
                "text": test_text,
                "speaker": SARVAM_SPEAKER,
                "language": SARVAM_LANGUAGE,
                "message": "Sarvam AI audio generated successfully"
            }
        else:
            return {"error": "Failed to generate audio with Sarvam AI"}, 500
            
    except Exception as e:
        safe_log('error', f"Sarvam AI test error: {str(e)}")
        return {"error": f"Test failed: {str(e)}"}, 500

# Speaker list endpoint
@app.route('/sarvam-speakers', methods=['GET'])
def sarvam_speakers():
    """List available Sarvam AI speakers"""
    return {
        "all_speakers": VALID_SARVAM_SPEAKERS,
        "female_speakers": FEMALE_SPEAKERS,
        "male_speakers": MALE_SPEAKERS,
        "current_speaker": SARVAM_SPEAKER,
        "validated_speaker": validate_sarvam_speaker(SARVAM_SPEAKER),
        "current_language": SARVAM_LANGUAGE
    }

# Translation test endpoint
@app.route('/test-translation', methods=['GET', 'POST'])
def test_translation():
    """Test Sarvam AI Translation integration"""
    try:
        text = request.args.get('text', 'Hello, how are you?')
        source_lang = request.args.get('source', 'auto')
        target_lang = request.args.get('target', USER_LANGUAGE)
        
        # Log configuration
        safe_log('info', f"Testing Sarvam AI Translation:")
        safe_log('info', f"API Key configured: {bool(SARVAM_API_KEY)}")
        safe_log('info', f"User Language: {USER_LANGUAGE}")
        safe_log('info', f"AI Language: {AI_LANGUAGE}")
        safe_log('info', f"USE_TRANSLATION: {USE_TRANSLATION}")
        
        if not SARVAM_API_KEY:
            return {"error": "SARVAM_API_KEY not configured in .env"}, 400
        
        translated_text = translate_text(text, source_lang, target_lang)
        
        return {
            "success": True,
            "original_text": text,
            "translated_text": translated_text,
            "source_language": source_lang,
            "target_language": target_lang,
            "translation_enabled": USE_TRANSLATION
        }
            
    except Exception as e:
        safe_log('error', f"Translation test error: {str(e)}")
        return {"error": f"Test failed: {str(e)}"}, 500

# --- Conversation Memory Functions ---
def get_call_session_id(request_form):
    """Extract or generate a unique call session ID from Twilio request"""
    call_sid = request_form.get('CallSid')
    if call_sid:
        return call_sid
    
    # Fallback: generate a temporary session ID
    return f"session_{str(uuid.uuid4())[:8]}"

def init_call_session(session_id: str):
    """Initialize a new call session with conversation history"""
    if session_id not in CALL_SESSIONS:
        CALL_SESSIONS[session_id] = {
            'conversation_history': [],
            'start_time': time.time(),
            'last_activity': time.time()
        }
        safe_log('info', f"Initialized call session: {session_id}")

def add_to_conversation_history(session_id: str, role: str, content: str):
    """Add a message to the conversation history"""
    if session_id in CALL_SESSIONS:
        CALL_SESSIONS[session_id]['conversation_history'].append({
            'role': role,
            'content': content,
            'timestamp': time.time()
        })
        CALL_SESSIONS[session_id]['last_activity'] = time.time()
        safe_log('info', f"Added to conversation history ({session_id}): {role} - {content[:50]}...")

def get_conversation_context(session_id: str) -> list:
    """Get conversation history formatted for OpenAI messages"""
    if session_id not in CALL_SESSIONS:
        return []
    
    messages = []
    for msg in CALL_SESSIONS[session_id]['conversation_history']:
        messages.append({
            'role': msg['role'],
            'content': msg['content']
        })
    
    return messages

def cleanup_old_sessions():
    """Clean up old conversation sessions (older than 1 hour)"""
    try:
        current_time = time.time()
        session_timeout = 3600  # 1 hour
        
        sessions_to_remove = []
        for session_id, session_data in CALL_SESSIONS.items():
            if current_time - session_data['last_activity'] > session_timeout:
                sessions_to_remove.append(session_id)
        
        for session_id in sessions_to_remove:
            CALL_SESSIONS.pop(session_id, None)
            safe_log('info', f"Cleaned up old session: {session_id}")
            
    except Exception as e:
        safe_log('error', f"Session cleanup error: {str(e)}")

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
        speechTimeout=SPEECH_TIMEOUT,
        profanityFilter="false",
        speechModel="phone_call"
    )
    
    # Use Sarvam AI or Polly based on configuration
    if USE_SARVAM_TTS and SARVAM_API_KEY:
        audio_id = generate_sarvam_audio(ai_reply)
        if audio_id:
            gather.play(f"{PUBLIC_URL}/audio/{audio_id}")
        else:
            # Fallback to Polly if Sarvam AI fails
            gather.say(ai_reply, voice="Polly.Kajal-Generative")
    else:
        gather.say(ai_reply, voice="Polly.Kajal-Generative")
    
    vr.append(gather)
    
    # Fallback if no speech detected
    fallback_text = "I didn't hear anything. Please try again."
    translated_fallback = translate_ai_response_to_user_language(fallback_text)
    
    if USE_SARVAM_TTS and SARVAM_API_KEY:
        fallback_audio_id = generate_sarvam_audio(translated_fallback)
        if fallback_audio_id:
            vr.play(f"{PUBLIC_URL}/audio/{fallback_audio_id}")
        else:
            vr.say(translated_fallback, voice="Polly.Kajal-Generative")
    else:
        vr.say(translated_fallback, voice="Polly.Kajal-Generative")
    
    vr.redirect(f"{PUBLIC_URL}/voice")
    
    return str(vr)

# --- Webhook: incoming call ---
@app.route("/voice", methods=["POST"])
def voice():
    # Initialize call session for conversation memory
    session_id = get_call_session_id(request.form)
    init_call_session(session_id)
    
    greeting_text = "Hello, I am AI assistant. Calling you on behalf of Aman Tech Innovation, may i have 2 mins of your time?"
    translated_greeting = translate_ai_response_to_user_language(greeting_text)
    
    # Add initial greeting to conversation history
    add_to_conversation_history(session_id, "assistant", greeting_text)
    
    return Response(
        twiml_with_reply(translated_greeting),
        mimetype="text/xml"
    )

# --- Webhook: AI response ---
@app.route("/ai-response", methods=["POST"])
def ai_response():
    try:
        # Get session ID for conversation memory
        session_id = get_call_session_id(request.form)
        init_call_session(session_id)  # Ensure session exists
        
        user_input = request.form.get("SpeechResult", "").strip()
        safe_log('info', f"AI-response triggered, user said: {user_input}")

        if not user_input:
            no_input_text = "I didn't catch that, could you please repeat?"
            translated_no_input = translate_ai_response_to_user_language(no_input_text)
            return Response(
                twiml_with_reply(translated_no_input),
                mimetype="text/xml"
            )

        # Exit phrases (check in both original and translated text)
        translated_input_for_check = translate_user_input_to_english(user_input) if USE_TRANSLATION else user_input
        exit_phrases = ["goodbye", "hang up", "stop", "bye", "end call", "thank you"]
        
        if (any(phrase in user_input.lower() for phrase in exit_phrases) or 
            any(phrase in translated_input_for_check.lower() for phrase in exit_phrases)):
            
            # Add goodbye exchange to conversation history
            add_to_conversation_history(session_id, "user", user_input)
            
            vr = VoiceResponse()
            goodbye_text = "Goodbye! Have a great day!"
            
            # Translate goodbye message to user's language
            translated_goodbye = translate_ai_response_to_user_language(goodbye_text)
            
            # Add goodbye to history
            add_to_conversation_history(session_id, "assistant", goodbye_text)
            
            if USE_SARVAM_TTS and SARVAM_API_KEY:
                goodbye_audio_id = generate_sarvam_audio(translated_goodbye)
                if goodbye_audio_id:
                    vr.play(f"{PUBLIC_URL}/audio/{goodbye_audio_id}")
                else:
                    vr.say(translated_goodbye, voice="Polly.Kajal-Generative")
            else:
                vr.say(translated_goodbye, voice="Polly.Kajal-Generative")
            
            vr.hangup()
            
            # Clean up session after call ends
            cleanup_old_sessions()
            
            return Response(str(vr), mimetype="text/xml")

        # Translate user input to English for AI processing
        translated_input = translate_user_input_to_english(user_input)
        safe_log('info', f"User input translated: '{user_input}' -> '{translated_input}'")
        
        # Add user input to conversation history
        add_to_conversation_history(session_id, "user", user_input)
        
        # Get AI reply via OpenAI Chat with conversation context
        ai_reply = get_ai_reply(translated_input, session_id)
        if not ai_reply:
            ai_reply = "I'm sorry, I'm having trouble processing that. Could you please try again?"
        
        # Add AI reply to conversation history
        add_to_conversation_history(session_id, "assistant", ai_reply)
        
        # Translate AI response back to user's preferred language
        translated_reply = translate_ai_response_to_user_language(ai_reply)
        safe_log('info', f"AI response translated: '{ai_reply}' -> '{translated_reply}'")
        return Response(twiml_with_reply(translated_reply, enable_stream=False), mimetype="text/xml")
        
    except Exception as e:
        safe_log('error', f"Error in ai_response: {str(e)}")
        # Return a safe fallback response instead of crashing
        vr = VoiceResponse()
        error_text = "I'm sorry, I encountered an error. Please try again."
        
        # Translate error message to user's language
        translated_error = translate_ai_response_to_user_language(error_text)
        
        if USE_SARVAM_TTS and SARVAM_API_KEY:
            error_audio_id = generate_sarvam_audio(translated_error)
            if error_audio_id:
                vr.play(f"{PUBLIC_URL}/audio/{error_audio_id}")
            else:
                vr.say(translated_error, voice="Polly.Kajal-Generative")
        else:
            vr.say(translated_error, voice="Polly.Kajal-Generative")
        
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
            'last_activity': time.time(),
            'speech_start_time': None,
            'silence_start_time': None,
            'is_speaking': False
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

    greeting_text = "Hello, I am AI assistant. Calling you on behalf of Aman Tech Innovation, may i have 2 mins of your time?"
    twiml = twiml_with_reply(translate_ai_response_to_user_language(greeting_text))
    call = client.calls.create(
        twiml=twiml,
        to=to_number,
        from_=TWILIO_NUMBER,
        record=True
    )
    return {'message': 'Call initiated', 'sid': call.sid}

# --- Debug endpoint for conversation sessions ---
@app.route('/debug/sessions', methods=['GET'])
def debug_sessions():
    """Debug endpoint to view active conversation sessions"""
    try:
        sessions_info = {}
        for session_id, session_data in CALL_SESSIONS.items():
            sessions_info[session_id] = {
                'start_time': session_data['start_time'],
                'last_activity': session_data['last_activity'],
                'conversation_count': len(session_data['conversation_history']),
                'conversation_history': session_data['conversation_history'][-5:]  # Last 5 messages
            }
        
        return {
            'active_sessions': len(CALL_SESSIONS),
            'sessions': sessions_info,
            'memory_info': f"Tracking {len(CALL_SESSIONS)} active conversations"
        }
    except Exception as e:
        safe_log('error', f"Debug sessions error: {str(e)}")
        return {"error": f"Debug failed: {str(e)}"}, 500

# --- OpenAI helpers ---
def get_ai_reply(prompt: str, session_id: str = None) -> str:
    try:
        if not prompt or not prompt.strip():
            return "I didn't catch that. Could you please repeat your question?"

        # Build messages with conversation context
        messages = [
            {"role": "system", "content": "You are Anushka, sales agent from Aman Tech Innovation (a company which does lead qualification, customer call and etc). "
                                          "Tell the purpose of the call which is as following: \n"
                                          "1. To check if user owns a business\n"
                                          "2. Do they have lot of outbound call.\n"
                                          "3. how many in estimate in a month.\n"
                                          "4. would they be interested in ai agent for calling their leads.\n\n"
                                          "Keep responses concise and conversational, suitable for voice interaction. "
                                          "Limit responses to 1-2 sentences. "
                                          "Remember the conversation context and refer to previous exchanges when relevant."}
        ]
        
        # Add conversation history if session exists
        if session_id:
            conversation_history = get_conversation_context(session_id)
            # Add previous conversation (exclude the current user message as it will be added below)
            messages.extend(conversation_history[:-1] if conversation_history else [])
        
        # Add current user message
        messages.append({"role": "user", "content": prompt})
        
        # Log conversation context for debugging
        safe_log('info', f"Sending {len(messages)} messages to OpenAI (session: {session_id})")

        resp = open_ai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        
        response = resp.choices[0].message.content.strip()
        return response if response else "I'm sorry, I couldn't generate a response. Please try again."
        
    except Exception as e:
        safe_log('error', f"OpenAI API error: {str(e)}")
        return "I'm sorry, I'm having trouble connecting to my AI service. Please try again in a moment."

# Periodic cleanup timer for conversation sessions
def start_periodic_cleanup():
    """Start a background thread to periodically clean up old sessions"""
    def cleanup_task():
        while True:
            try:
                time.sleep(600)  # Run cleanup every 10 minutes
                cleanup_old_sessions()
            except Exception as e:
                safe_log('error', f"Periodic cleanup error: {str(e)}")
    
    cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
    cleanup_thread.start()
    safe_log('info', "Started periodic session cleanup thread")

if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    
    # Start periodic cleanup
    start_periodic_cleanup()
    
    port = int(os.getenv("PORT", 8000))
    safe_log('info', f"Starting voice assistant server on port {port} with conversation memory")
    pywsgi.WSGIServer(("0.0.0.0", port), app, handler_class=WebSocketHandler).serve_forever()
