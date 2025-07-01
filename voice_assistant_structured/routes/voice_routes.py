from flask import Blueprint, request, Response
from twilio.twiml.voice_response import VoiceResponse
from config import Config
from utils.logger import safe_log
from models.session import session_manager
from services import sarvam_service, twilio_service, openai_service

voice_bp = Blueprint('voice', __name__)

@voice_bp.route("/voice", methods=["POST"])
def voice():
    """Handle incoming call - initial greeting"""
    # Initialize call session for conversation memory
    session_id = session_manager.get_session_id_from_request(request.form)
    session_manager.init_session(session_id)
    
    greeting_text = "Hello, I am AI assistant. Calling you on behalf of Aman Tech Innovation, may i have 2 mins of your time?"
    translated_greeting = sarvam_service.translate_ai_response_to_user_language(greeting_text)
    
    # Add initial greeting to conversation history
    session_manager.add_to_conversation(session_id, "assistant", greeting_text)
    
    return Response(
        twilio_service.generate_twiml_with_reply(translated_greeting),
        mimetype="text/xml"
    )

@voice_bp.route("/ai-response", methods=["POST"])
def ai_response():
    """Handle user speech input and generate AI response"""
    try:
        # Get session ID for conversation memory
        session_id = session_manager.get_session_id_from_request(request.form)
        session_manager.init_session(session_id)  # Ensure session exists
        
        user_input = request.form.get("SpeechResult", "").strip()
        safe_log('info', f"AI-response triggered, user said: {user_input}")

        if not user_input:
            no_input_text = "I didn't catch that, could you please repeat?"
            translated_no_input = sarvam_service.translate_ai_response_to_user_language(no_input_text)
            return Response(
                twilio_service.generate_twiml_with_reply(translated_no_input),
                mimetype="text/xml"
            )

        # Exit phrases (check in both original and translated text)
        translated_input_for_check = sarvam_service.translate_user_input_to_english(user_input) if Config.USE_TRANSLATION else user_input
        exit_phrases = ["goodbye", "hang up", "stop", "bye", "end call", "thank you"]
        
        if (any(phrase in user_input.lower() for phrase in exit_phrases) or 
            any(phrase in translated_input_for_check.lower() for phrase in exit_phrases)):
            
            # Add goodbye exchange to conversation history
            session_manager.add_to_conversation(session_id, "user", user_input)
            
            vr = VoiceResponse()
            goodbye_text = "Goodbye! Have a great day!"
            
            # Translate goodbye message to user's language
            translated_goodbye = sarvam_service.translate_ai_response_to_user_language(goodbye_text)
            
            # Add goodbye to history
            session_manager.add_to_conversation(session_id, "assistant", goodbye_text)
            
            if Config.USE_SARVAM_TTS and Config.SARVAM_API_KEY:
                goodbye_audio_id = sarvam_service.generate_audio(translated_goodbye)
                if goodbye_audio_id:
                    vr.play(f"{Config.PUBLIC_URL}/audio/{goodbye_audio_id}")
                else:
                    vr.say(translated_goodbye, voice="Polly.Kajal-Generative")
            else:
                vr.say(translated_goodbye, voice="Polly.Kajal-Generative")
            
            vr.hangup()
            
            # Clean up session after call ends
            session_manager.cleanup_expired_sessions()
            
            return Response(str(vr), mimetype="text/xml")

        # Translate user input to English for AI processing
        translated_input = sarvam_service.translate_user_input_to_english(user_input)
        safe_log('info', f"User input translated: '{user_input}' -> '{translated_input}'")
        
        # Add user input to conversation history
        session_manager.add_to_conversation(session_id, "user", user_input)
        
        # Get AI reply via OpenAI Chat with conversation context
        ai_reply = openai_service.get_ai_reply(translated_input, session_id)
        if not ai_reply:
            ai_reply = "I'm sorry, I'm having trouble processing that. Could you please try again?"
        
        # Add AI reply to conversation history
        session_manager.add_to_conversation(session_id, "assistant", ai_reply)
        
        # Translate AI response back to user's preferred language
        translated_reply = sarvam_service.translate_ai_response_to_user_language(ai_reply)
        safe_log('info', f"AI response translated: '{ai_reply}' -> '{translated_reply}'")
        
        return Response(
            twilio_service.generate_twiml_with_reply(translated_reply, enable_stream=False), 
            mimetype="text/xml"
        )
        
    except Exception as e:
        safe_log('error', f"Error in ai_response: {str(e)}")
        # Return a safe fallback response instead of crashing
        vr = VoiceResponse()
        error_text = "I'm sorry, I encountered an error. Please try again."
        
        # Translate error message to user's language
        translated_error = sarvam_service.translate_ai_response_to_user_language(error_text)
        
        if Config.USE_SARVAM_TTS and Config.SARVAM_API_KEY:
            error_audio_id = sarvam_service.generate_audio(translated_error)
            if error_audio_id:
                vr.play(f"{Config.PUBLIC_URL}/audio/{error_audio_id}")
            else:
                vr.say(translated_error, voice="Polly.Kajal-Generative")
        else:
            vr.say(translated_error, voice="Polly.Kajal-Generative")
        
        vr.redirect(f"{Config.PUBLIC_URL}/voice")
        return Response(str(vr), mimetype="text/xml")

@voice_bp.route("/make-call", methods=["POST"])
def make_call():
    """Initiate an outbound call"""
    to_number = request.form.get('to')
    if not to_number:
        return {'error': "Missing 'to' number"}, 400

    greeting_text = "Hello, I am AI assistant. Calling you on behalf of Aman Tech Innovation, may i have 2 mins of your time?"
    translated_greeting = sarvam_service.translate_ai_response_to_user_language(greeting_text)
    
    result = twilio_service.make_outbound_call(to_number, translated_greeting)
    return result