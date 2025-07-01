from openai import OpenAI
from config import Config
from utils.logger import safe_log
from models.session import session_manager

class OpenAIService:
    """Service for handling OpenAI API interactions"""
    
    def __init__(self):
        self.client = self._initialize_client()
    
    def _initialize_client(self):
        """Initialize OpenAI client with appropriate configuration"""
        if Config.OPENAI_API_KEY:
            safe_log('info', "Initializing OpenAI client")
            return OpenAI(api_key=Config.OPENAI_API_KEY)
        elif all([Config.AZURE_OPENAI_API_KEY, Config.AZURE_OPENAI_ENDPOINT]):
            safe_log('info', "Initializing Azure OpenAI client")
            return OpenAI(
                api_key=Config.AZURE_OPENAI_API_KEY,
                base_url=f"{Config.AZURE_OPENAI_ENDPOINT}/openai/deployments/{Config.AZURE_OPENAI_DEPLOYMENT_NAME}",
                default_headers={"api-version": Config.AZURE_OPENAI_VERSION}
            )
        else:
            raise ValueError("Missing OpenAI configuration")
    
    def get_ai_reply(self, prompt: str, session_id: str = None) -> str:
        """Get AI reply with conversation context"""
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
                conversation_history = session_manager.get_conversation_context(session_id)
                # Add previous conversation (exclude the current user message as it will be added below)
                safe_log('info', f"Conversation History:\n {conversation_history}\n\n\n)")

                print(conversation_history)
                messages.extend(conversation_history[:-1] if conversation_history else [])
            
            # Add current user message
            messages.append({"role": "user", "content": prompt})
            
            # Log conversation context for debugging
            safe_log('info', f"Sending {len(messages)} messages to OpenAI (session: {session_id})")

            resp = self.client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=messages,
                max_tokens=150,
                temperature=0.7
            )
            
            response = resp.choices[0].message.content.strip()
            return response if response else "I'm sorry, I couldn't generate a response. Please try again."
            
        except Exception as e:
            safe_log('error', f"OpenAI API error: {str(e)}")
            return "I'm sorry, I'm having trouble connecting to my AI service. Please try again in a moment."
    
    def transcribe_audio(self, audio_file_path: str) -> str:
        """Transcribe audio using Whisper"""
        try:
            with open(audio_file_path, 'rb') as audio_file:
                resp = self.client.audio.transcriptions.create(
                    model=Config.WHISPER_MODEL,
                    file=audio_file,
                    language="en",
                    response_format="text"
                )
            
            result = resp if isinstance(resp, str) else getattr(resp, 'text', '')
            return result.strip()
            
        except Exception as e:
            safe_log('error', f"Whisper transcription error: {str(e)}")
            return ""

# Global OpenAI service instance
openai_service = OpenAIService()