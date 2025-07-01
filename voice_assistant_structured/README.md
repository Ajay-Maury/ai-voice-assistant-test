# AI Voice Assistant - Structured Version

A well-structured Twilio AI Voice Assistant with conversation memory, multilingual support, and Sarvam AI integration.

## 📁 Project Structure

```
voice_assistant_structured/
├── app.py                 # Main application entry point
├── requirements.txt       # Python dependencies
├── env.sample            # Environment variables template
├── .gitignore           # Git ignore rules
├── README.md            # This file
├── config/              # Configuration management
│   ├── __init__.py
│   └── settings.py      # Application settings and env vars
├── models/              # Data models and session management
│   ├── __init__.py
│   └── session.py       # Call session and conversation memory
├── services/            # Business logic and external API integrations
│   ├── __init__.py
│   ├── openai_service.py    # OpenAI/Azure OpenAI integration
│   ├── sarvam_service.py    # Sarvam AI TTS and Translation
│   ├── twilio_service.py    # Twilio operations and TwiML
│   └── websocket_service.py # WebSocket handling
├── routes/              # Flask route handlers
│   ├── __init__.py
│   ├── voice_routes.py      # Main voice call endpoints
│   ├── audio_routes.py      # Audio file serving
│   ├── test_routes.py       # Testing and debug endpoints
│   └── websocket_routes.py  # WebSocket route setup
└── utils/               # Utility functions
    ├── __init__.py
    ├── logger.py            # Safe logging utilities
    └── audio.py             # Audio processing utilities
```

## 🚀 Features

- **Conversation Memory**: Remembers the entire conversation within a single call
- **Multilingual Support**: Automatic translation between user and AI languages
- **Sarvam AI Integration**: High-quality Indian language TTS and translation
- **WebSocket Streaming**: Real-time audio streaming support
- **Modular Architecture**: Well-organized, maintainable code structure
- **Error Handling**: Robust error handling and fallback mechanisms
- **Session Management**: Automatic cleanup of old conversation sessions

## 🛠 Installation

1. **Clone and navigate to the structured directory:**
   ```bash
   cd voice_assistant_structured
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup environment variables:**
   ```bash
   cp env.sample .env
   # Edit .env with your actual API keys and configuration
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

## 🔧 Configuration

The application uses environment variables for configuration. Key settings include:

### Required Variables
- `TWILIO_ACCOUNT_SID`: Your Twilio Account SID
- `TWILIO_AUTH_TOKEN`: Your Twilio Auth Token  
- `TWILIO_PHONE_NUMBER`: Your Twilio phone number
- `OPENAI_API_KEY`: OpenAI API key (or Azure OpenAI credentials)

### Optional Variables
- `SARVAM_API_KEY`: Sarvam AI API key for TTS and translation
- `USER_LANGUAGE`: User's preferred language (default: kn-IN)
- `AI_LANGUAGE`: AI processing language (default: en-IN)
- `USE_TRANSLATION`: Enable automatic translation (default: true)
- `USE_SARVAM_TTS`: Use Sarvam AI for TTS (default: false)

## 📡 API Endpoints

### Voice Endpoints
- `POST /voice` - Handle incoming calls
- `POST /ai-response` - Process user speech and generate AI responses
- `POST /make-call` - Initiate outbound calls

### Audio Endpoints
- `GET /audio/<audio_id>` - Serve generated audio files

### Test Endpoints
- `GET /test-sarvam` - Test Sarvam AI TTS integration
- `GET /test-translation` - Test translation functionality
- `GET /sarvam-speakers` - List available Sarvam AI speakers
- `GET /debug/sessions` - View active conversation sessions

### WebSocket Endpoints
- `WSS /stream` - Handle Twilio media streams

## 🧠 Architecture Benefits

### Separation of Concerns
- **Config**: Centralized configuration management
- **Models**: Data structures and session management
- **Services**: Business logic and external API integrations
- **Routes**: HTTP request handling
- **Utils**: Reusable utility functions

### Maintainability
- **Single Responsibility**: Each module has a clear, focused purpose
- **Dependency Injection**: Services can be easily tested and replaced
- **Error Isolation**: Errors in one module don't affect others
- **Code Reusability**: Common functionality is shared across modules

### Scalability
- **Modular Design**: Easy to add new features or modify existing ones
- **Service-Based**: External services can be swapped or extended
- **Session Management**: Efficient memory usage and cleanup
- **Async Support**: Ready for async operations and concurrent requests

## 🔄 Migration from Monolithic

This structured version maintains full compatibility with the original `voice_assistant.py` while providing:

1. **Better Organization**: Code is logically separated into modules
2. **Easier Testing**: Each component can be tested independently
3. **Improved Debugging**: Issues can be traced to specific modules
4. **Enhanced Maintainability**: Changes are isolated to relevant modules
5. **Team Collaboration**: Multiple developers can work on different modules

## 🚀 Usage

```bash
# Development mode
export DEBUG=true
python app.py

# Production mode (default)
python app.py
```

The application will start with conversation memory enabled and all features from the original version, but with improved structure and maintainability.

## 🔍 Key Improvements

1. **Conversation Memory**: Tracks full conversation history per call session
2. **Modular Services**: Each external API has its own service module
3. **Configuration Management**: Centralized settings with validation
4. **Error Handling**: Comprehensive error handling across all modules
5. **Session Cleanup**: Automatic cleanup of expired conversation sessions
6. **Debug Endpoints**: Built-in debugging and monitoring capabilities