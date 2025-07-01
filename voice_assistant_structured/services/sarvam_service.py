import base64
import requests
import uuid
import tempfile
import os
from config import Config
from utils.logger import safe_log

class SarvamService:
    """Service for handling Sarvam AI TTS and Translation"""
    
    # Valid speakers based on API documentation
    VALID_SPEAKERS = [
        'meera', 'pavithra', 'maitreyi', 'arvind', 'amol', 'amartya', 
        'diya', 'neel', 'misha', 'vian', 'arjun', 'maya', 'anushka', 
        'abhilash', 'manisha', 'vidya', 'arya', 'karun', 'hitesh'
    ]
    
    FEMALE_SPEAKERS = ['meera', 'pavithra', 'maitreyi', 'diya', 'misha', 'maya', 'anushka', 'manisha', 'vidya', 'arya']
    MALE_SPEAKERS = ['arvind', 'amol', 'amartya', 'neel', 'vian', 'arjun', 'abhilash', 'karun', 'hitesh']
    
    def __init__(self):
        self.api_key = Config.SARVAM_API_KEY
        self.audio_storage = {}
    
    def validate_speaker(self, speaker: str) -> str:
        """Validate and correct speaker name if needed"""
        if speaker.lower() in self.VALID_SPEAKERS:
            return speaker.lower()
        
        # Try to find closest match
        speaker_lower = speaker.lower()
        for valid_speaker in self.VALID_SPEAKERS:
            if speaker_lower in valid_speaker or valid_speaker in speaker_lower:
                safe_log('warning', f"Speaker '{speaker}' corrected to '{valid_speaker}'")
                return valid_speaker
        
        # Default fallback
        safe_log('warning', f"Invalid speaker '{speaker}', using default 'manisha'")
        return 'manisha'
    
    def generate_audio(self, text: str) -> str:
        """Generate audio using Sarvam AI TTS API and return audio ID"""
        try:
            safe_log('info', f"Attempting Sarvam AI TTS for text: {text[:50]}...")
            
            if not self.api_key:
                safe_log('error', "Sarvam AI API key not configured")
                return None
                
            url = "https://api.sarvam.ai/text-to-speech"
            
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": self.api_key
            }
            
            # Truncate text if too long (max 1500 characters)
            if len(text) > 1500:
                text = text[:1497] + "..."
                safe_log('warning', f"Text truncated to 1500 characters for Sarvam AI")

            # Validate and correct speaker name
            validated_speaker = self.validate_speaker(Config.SARVAM_SPEAKER)
            
            data = {
                "text": text,
                "target_language_code": Config.SARVAM_LANGUAGE,
                "speaker": validated_speaker,
                "pitch": Config.SARVAM_PITCH,
                "pace": Config.SARVAM_PACE,
                "loudness": Config.SARVAM_LOUDNESS
            }
            
            safe_log('info', f"Making Sarvam AI request with speaker: {validated_speaker}, language: {Config.SARVAM_LANGUAGE}")
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
                    self.audio_storage[audio_id] = filepath
                    
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
    
    def get_audio_file_path(self, audio_id: str) -> str:
        """Get file path for audio ID"""
        return self.audio_storage.get(audio_id)
    
    def cleanup_audio(self, audio_id: str):
        """Clean up audio file"""
        if audio_id in self.audio_storage:
            filepath = self.audio_storage[audio_id]
            try:
                if os.path.exists(filepath):
                    os.unlink(filepath)
                self.audio_storage.pop(audio_id, None)
            except Exception as e:
                safe_log('error', f"Audio cleanup error: {str(e)}")
    
    def translate_text(self, text: str, source_language: str = "auto", target_language: str = "en-IN") -> str:
        """Translate text using Sarvam AI Translation API"""
        try:
            safe_log('info', f"Translating text from {source_language} to {target_language}: {text[:50]}...")
            
            if not self.api_key:
                safe_log('error', "Sarvam AI API key not configured for translation")
                return text
                
            url = "https://api.sarvam.ai/translate"
            
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": self.api_key
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
                return text
                
        except Exception as e:
            safe_log('error', f"Sarvam AI translation error: {str(e)}")
            return text
    
    def translate_user_input_to_english(self, user_input: str) -> str:
        """Translate user input from their preferred language to English for AI processing"""
        if not Config.USE_TRANSLATION or not user_input.strip():
            return user_input
        
        if Config.USER_LANGUAGE == Config.AI_LANGUAGE:
            return user_input  # No translation needed
        
        return self.translate_text(user_input, source_language="auto", target_language=Config.AI_LANGUAGE)

    def translate_ai_response_to_user_language(self, ai_response: str) -> str:
        """Translate AI response from English to user's preferred language"""
        if not Config.USE_TRANSLATION or not ai_response.strip():
            return ai_response
        
        if Config.AI_LANGUAGE == Config.USER_LANGUAGE:
            return ai_response  # No translation needed
        
        return self.translate_text(ai_response, source_language=Config.AI_LANGUAGE, target_language=Config.USER_LANGUAGE)

# Global Sarvam service instance
sarvam_service = SarvamService()