from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Connect, Stream
from config import Config
from utils.logger import safe_log
from .sarvam_service import sarvam_service

class TwilioService:
    """Service for handling Twilio operations"""
    
    def __init__(self):
        self.client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
    
    def generate_twiml_with_reply(self, ai_reply: str, enable_stream: bool = False) -> str:
        """Generate TwiML response with barge-in gather"""
        vr = VoiceResponse()
        
        # 1) Start media stream (only if flask-sockets is working properly)
        if enable_stream:
            try:
                connect = Connect()
                # Extract host from PUBLIC_URL
                stream_host = Config.PUBLIC_URL.replace('https://', '').replace('http://', '')
                connect.append(Stream(url=f"wss://{stream_host}/stream"))
                vr.append(connect)
                safe_log('info', f"Added WebSocket stream to TwiML: wss://{stream_host}/stream")
            except Exception as e:
                safe_log('error', f"Failed to add WebSocket stream: {str(e)}")

        # 2) Barge-in gather with voice selection
        gather = Gather(
            input="speech",
            bargeIn=True,
            action=f"{Config.PUBLIC_URL}/ai-response",
            method="POST",
            speechTimeout=Config.SPEECH_TIMEOUT,
            profanityFilter="false",
            speechModel="phone_call"
        )
        
        # Use Sarvam AI or Polly based on configuration
        if Config.USE_SARVAM_TTS and Config.SARVAM_API_KEY:
            audio_id = sarvam_service.generate_audio(ai_reply)
            if audio_id:
                gather.play(f"{Config.PUBLIC_URL}/audio/{audio_id}")
            else:
                # Fallback to Polly if Sarvam AI fails
                gather.say(ai_reply, voice="Polly.Kajal-Generative")
        else:
            gather.say(ai_reply, voice="Polly.Kajal-Generative")
        
        vr.append(gather)
        
        # Fallback if no speech detected
        fallback_text = "I didn't hear anything. Please try again."
        translated_fallback = sarvam_service.translate_ai_response_to_user_language(fallback_text)
        
        if Config.USE_SARVAM_TTS and Config.SARVAM_API_KEY:
            fallback_audio_id = sarvam_service.generate_audio(translated_fallback)
            if fallback_audio_id:
                vr.play(f"{Config.PUBLIC_URL}/audio/{fallback_audio_id}")
            else:
                vr.say(translated_fallback, voice="Polly.Kajal-Generative")
        else:
            vr.say(translated_fallback, voice="Polly.Kajal-Generative")
        
        vr.redirect(f"{Config.PUBLIC_URL}/voice")
        
        return str(vr)
    
    def make_outbound_call(self, to_number: str, greeting_text: str) -> dict:
        """Make an outbound call"""
        try:
            twiml = self.generate_twiml_with_reply(greeting_text)
            call = self.client.calls.create(
                twiml=twiml,
                to=to_number,
                from_=Config.TWILIO_NUMBER,
                record=True
            )
            return {'message': 'Call initiated', 'sid': call.sid}
        except Exception as e:
            safe_log('error', f"Failed to make outbound call: {str(e)}")
            return {'error': str(e)}

# Global Twilio service instance
twilio_service = TwilioService()