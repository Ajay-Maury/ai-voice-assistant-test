import os
from dotenv import load_dotenv

load_dotenv()
# You are a friendly, conversational human assistant, manisha.
# Respond naturally and warmly, as if you are speaking to a friend.
# Keep responses concise and conversational, suitable for voice interaction.
# Limit responses to 1-2 sentences. if its in hindi, try to reply in hinglish like how informally its spoken unless user. 
# and otherwise whatever the language is use a cheerful tone with same language.
# And also greet the user Aman at the starting of the conversation.


AI_SYSTEM_PROMPT = """You are Manisha, a friendly and conversational voice agent from Aman Tech Innovations.

Your job is to engage the user in a natural, voice-friendly way and introduce our Voice AI bot solution that helps businesses automate outbound calls and customer engagement.

Follow these general instructions for the conversation:

1. **Greet and Introduce Yourself**
   - Always start warmly by greeting the user by name (e.g., "Hi Aman") and saying you're calling from Aman Tech Innovations.
   
2. **State the Purpose Clearly**
   - Briefly explain that you're calling to introduce a Voice AI bot that can help automate customer conversations.

3. **Ask for Permission**
   - Politely ask if it's a good time to share more about how it could help their business.

4. **Qualify the User**
   - Ask if they run a business or work with businesses.
   - If yes, ask if their business involves outbound calls (e.g., sales, support, reminders).
   - Then ask for an idea of the outbound call volume — daily, monthly, or yearly.

5. **Style & Language**
   - Keep responses short, friendly, and suitable for voice (1-2 sentences max).
   - Use a cheerful and conversational tone.
   - If the user speaks Hindi, respond in informal Hinglish unless they ask otherwise.
   - Match the language and tone of the user to maintain a natural flow.

---

**Sample Conversation Opening**:

"Hi Aman, this is Manisha calling from Aman Tech Innovations!  
I'm just calling to quickly introduce a Voice AI bot we've built — it helps automate outbound calls and customer engagement.  
Do you have a quick minute for me to share how it might help your business?"

"""


INITIAL_GREETING_TEXT = "Hi there, this is Manisha from Omen Tech Innovations! Kya aap kisi business ko chalate hain ya kisi aise business ke saath kaam karte hain jo customer calls handle karta hai?"

# Predefined user engagement expressions
ENGAGEMENT_WORDS = {
    # Common Hinglish acknowledgements
    "haan", "ha", "hanji", "haanji", "hmm", "hmm hmm", "hmmhmm", "huh", "huh huh", "uh huh",
    "hum", "ji", "hmm ji", "hmm haan", "hmm haanji", "hmm hanji",
    
    # Variants of "ok", "fine", "alright"
    "ok", "okay", "ok ok", "okay okay", "okey", "alright", "right", "fine", "cool", "done", "perfect", "great", "nice",
    "hmm okay", "hmm ok", "hmm fine", "hmm great", "hmm nice", "hmm perfect", "hmm done", "sounds good", "makes sense",
    
    # Hindi acknowledgements
    "achha", "accha", "acha", "thik hai", "theek hai", "theek", "samjha", "samajh gaya", "hmm samajh gaya", "hmm samjha",
    "sahi", "hmm sahi", "hmm theek", "hmm thik", "hmm achha", "hmm accha", "hmm acha",
    
    # Basic affirmatives
    "yes", "yeah", "yup", "i see", "got it", "i got it", "understood", "noted", "sure", "okay sure", "yes yes",
    
    # Expressions often used in non-intent fillers
    "oh", "ohh", "oh okay", "ohh okay", "ohk", "hmm oh", "hmm ohk", "hmm hmm hmm", "hmm noted", "hmm sure",

    # Polite closures or filler
    "thank you", "thanks", "thanks a lot", "thankyou", "thank u", "thankyou so much", "thanks so much",

    # Connectors (used as filler)
    "and", "or", "yeah yeah", "ya", "yaar", "bas", "thik", "hmm thik hai", "hmm theek hai", "thik thak",

    # Friendly passive tone
    "hmm hmm hmm", "mmm", "mmm hmm", "nice nice", "great great",

    # Random casual fillers
    "Thank you for watching!"
}

AUDIO_CHUNK_DIR = "audio_chunks"
os.makedirs(AUDIO_CHUNK_DIR, exist_ok=True)

RESPONSE_AUDIO_CHUNK_DIR = "response_audio_chunks"
os.makedirs(RESPONSE_AUDIO_CHUNK_DIR, exist_ok=True)

AUDIO_SILENCE_THRESHOLDS = {
    "MAX_AMPLITUDE": 10000,  # If any sample exceeds this, it's not silent
    "MIN_RMS_DBFS": -30.0,  # If average energy (RMS in dBFS) is above this, it's not silent
}

AUDIO_CACHE_DIR = "static/audio_cache"
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

AUDIO_CHUNK_SIZE = 160  # Size of audio chunks in bytes (20ms at 8000Hz) 
AUDIO_SAMPLE_RATE = 8000  # Sample rate for audio
SILENCE_MAX_DURATION=0.8  # Max seconds of silence to be added in audio buffer  s
AUDIO_BUFFER_SILENCE = 1.5  # Seconds of silence to wait before processing audio
# MIN_AUDIO_BYTES = 8000 * 0.75  # 8000 samples * 0.75 sec of bytes of μ-law audio at 8kHz
MIN_AUDIO_BYTES = 6000  # ≈ 0.125 seconds of μ-law audio at 8kHz

VAD_MIN_SILENCE_FRAMES = 5  # Minimum silent frames to consider end of speech
VAD_FRAME_SIZE = 320  # Size of each VAD frame in samples (20ms at 16kHz)

ENGAGEMENT_RESPONSES = {
    "ENGAGED": {
        "en": ["hmm", "okay", "got it", "yeah"],
        "hi": ["हां", "अच्छा", "ओके", "ठीक है"]
        # Add more languages here
    },
    "DISENGAGED": {
        "en": ["Are you there?", "Still with me?", "Can you hear me?"],
        "hi": ["क्या आप अभी भी लाइन पर हैं?", "क्या मेरी बात सुन पा रहे हैं?", "आपकी आवाज़ नहीं आ रही है!",],
        # Add more languages here
    }
}

ENGAGEMENT_TRIGGER_SECONDS = 3.0                         # seconds of continuous speech
ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY = 3.0                # repeat interval for engagement task
DISENGAGEMENT_TRIGGER_SECONDS = 10.0                     # seconds of silence
DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY = 5.0             # repeat interval for disengagement task

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = str(os.getenv("TWILIO_PHONE_NUMBER"))
VERIFIED_TEST_NUMBER = os.getenv("VERIFIED_TEST_NUMBER")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "whisper-1")

WHISPER_STT_OFFLINE_MODEL = os.getenv("WHISPER_STT_OFFLINE_MODEL", "medium")    # "medium" for better accuracy

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
print("GROQ_API_KEY", GROQ_API_KEY)
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
GROQ_CHAT_TEMPERATURE = float(os.getenv("GROQ_CHAT_TEMPERATURE", 0.4))

REDIS_URL = os.getenv("REDIS_URL")
WEB_SOCKET_URL = os.getenv("WEBSOCKET_URL")
VOICE_ROUTE_URL = os.getenv("VOICE_ROUTE_URL")

SARVAM_SUBSCRIPTION_KEY=os.getenv("SARVAM_API_KEY")
SARVAM_VOICE=os.getenv("SARVAM_SPEAKER", "anushka")
SARVAM_LANGUAGE=os.getenv("SARVAM_LANGUAGE", "hi-IN")
SARVAM_TTS_MODEL=os.getenv("SARVAM_TTS_MODEL", "bulbul:v2")
SARVAM_STT_MODEL=os.getenv("SARVAM_STT_MODEL","saarika:v2.5")
SARVAM_PACE=float(os.getenv("SARVAM_PACE", 1.0))

TAVILY_API_KEY=os.getenv("TAVILY_API_KEY","tvly-Cn5d0xe")
