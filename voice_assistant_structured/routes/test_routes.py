from flask import Blueprint, request
from config import Config
from utils.logger import safe_log
from services import sarvam_service
from models.session import session_manager

test_bp = Blueprint('test', __name__)

@test_bp.route('/test-sarvam', methods=['GET', 'POST'])
def test_sarvam():
    """Test Sarvam AI TTS integration"""
    try:
        test_text = request.args.get('text', 'Hello, this is a test of Sarvam AI voice synthesis in Kannada. ಇದು ಸರ್ವಮ್ AI ಧ್ವನಿ ಸಂಶ್ಲೇಷಣೆಯ ಪರೀಕ್ಷೆಯಾಗಿದೆ.')
        
        # Log configuration
        safe_log('info', f"Testing Sarvam AI with:")
        safe_log('info', f"API Key configured: {bool(Config.SARVAM_API_KEY)}")
        safe_log('info', f"Speaker: {Config.SARVAM_SPEAKER}")
        safe_log('info', f"Language: {Config.SARVAM_LANGUAGE}")
        safe_log('info', f"USE_SARVAM_TTS: {Config.USE_SARVAM_TTS}")
        
        if not Config.USE_SARVAM_TTS:
            return {"error": "Sarvam AI is disabled. Set USE_SARVAM_TTS=true in .env"}, 400
        
        if not Config.SARVAM_API_KEY:
            return {"error": "SARVAM_API_KEY not configured in .env"}, 400
        
        audio_id = sarvam_service.generate_audio(test_text)
        
        if audio_id:
            audio_url = f"{Config.PUBLIC_URL}/audio/{audio_id}"
            return {
                "success": True,
                "audio_id": audio_id,
                "audio_url": audio_url,
                "text": test_text,
                "speaker": Config.SARVAM_SPEAKER,
                "language": Config.SARVAM_LANGUAGE,
                "message": "Sarvam AI audio generated successfully"
            }
        else:
            return {"error": "Failed to generate audio with Sarvam AI"}, 500
            
    except Exception as e:
        safe_log('error', f"Sarvam AI test error: {str(e)}")
        return {"error": f"Test failed: {str(e)}"}, 500

@test_bp.route('/sarvam-speakers', methods=['GET'])
def sarvam_speakers():
    """List available Sarvam AI speakers"""
    return {
        "all_speakers": sarvam_service.VALID_SPEAKERS,
        "female_speakers": sarvam_service.FEMALE_SPEAKERS,
        "male_speakers": sarvam_service.MALE_SPEAKERS,
        "current_speaker": Config.SARVAM_SPEAKER,
        "validated_speaker": sarvam_service.validate_speaker(Config.SARVAM_SPEAKER),
        "current_language": Config.SARVAM_LANGUAGE
    }

@test_bp.route('/test-translation', methods=['GET', 'POST'])
def test_translation():
    """Test Sarvam AI Translation integration"""
    try:
        text = request.args.get('text', 'Hello, how are you?')
        source_lang = request.args.get('source', 'auto')
        target_lang = request.args.get('target', Config.USER_LANGUAGE)
        
        # Log configuration
        safe_log('info', f"Testing Sarvam AI Translation:")
        safe_log('info', f"API Key configured: {bool(Config.SARVAM_API_KEY)}")
        safe_log('info', f"User Language: {Config.USER_LANGUAGE}")
        safe_log('info', f"AI Language: {Config.AI_LANGUAGE}")
        safe_log('info', f"USE_TRANSLATION: {Config.USE_TRANSLATION}")
        
        if not Config.SARVAM_API_KEY:
            return {"error": "SARVAM_API_KEY not configured in .env"}, 400
        
        translated_text = sarvam_service.translate_text(text, source_lang, target_lang)
        
        return {
            "success": True,
            "original_text": text,
            "translated_text": translated_text,
            "source_language": source_lang,
            "target_language": target_lang,
            "translation_enabled": Config.USE_TRANSLATION
        }
            
    except Exception as e:
        safe_log('error', f"Translation test error: {str(e)}")
        return {"error": f"Test failed: {str(e)}"}, 500

@test_bp.route('/debug/sessions', methods=['GET'])
def debug_sessions():
    """Debug endpoint to view active conversation sessions"""
    try:
        return session_manager.get_active_sessions_info()
    except Exception as e:
        safe_log('error', f"Debug sessions error: {str(e)}")
        return {"error": f"Debug failed: {str(e)}"}, 500