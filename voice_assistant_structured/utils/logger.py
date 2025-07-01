import logging

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('voice_assistant.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

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