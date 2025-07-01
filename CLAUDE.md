1# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Twilio AI Voice Assistant Prototype** that demonstrates comprehensive voice communication capabilities using Twilio's API combined with AI technologies (OpenAI GPT-4 and Whisper). The application supports both traditional IVR systems and advanced AI-powered conversational interfaces.

## Architecture

The project has a **dual-server architecture**:

- **`voice_assistant.py`**: AI-powered conversational voice assistant with real-time WebSocket streaming
- **`server.py`**: Traditional Flask IVR server for simple menu-driven interactions

### Core Voice Processing Pipeline
```
Incoming Call → Twilio → Webhook → Flask App → WebSocket Stream → 
Audio Buffer → Whisper → Text → GPT-4 → Response → TTS → Caller
```

## Common Development Commands

### Running the Applications
```bash
# AI-powered voice assistant (main application)
python voice_assistant.py

# Traditional IVR server
python server.py

# Outbound call utility
python app/voice_outgoing.py

# SMS sending utility
python app/sms.py

# Scheduled call automation (runs continuously)
python app/scheduler.py
```

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp env.sample .env
# Edit .env with your credentials
```

### Testing with ngrok
```bash
# Expose local server for Twilio webhooks
ngrok http 5000
# Use the ngrok URL in Twilio Console webhooks
```

## Key Environment Variables

The application supports multiple AI providers and services:

### Required Twilio Configuration
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- `VERIFIED_TEST_NUMBER` for testing

### AI Provider Options
- **Azure OpenAI**: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`
- **OpenAI Direct**: `OPENAI_API_KEY`
- **Neo4j Knowledge Graph**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

### Additional Integrations
- **WhatsApp**: `WHATSAPP_SANDBOX_NUMBER`
- **SendGrid**: `SENDGRID_API_KEY`

## File Structure and Responsibilities

### Main Applications
- **`voice_assistant.py`**: AI voice assistant with real-time audio streaming, barge-in capability, and GPT-4 integration
- **`server.py`**: Flask IVR server with traditional menu-driven responses and SMS auto-reply

### Utility Scripts (`/app/` directory)
- **`voice_outgoing.py`**: Simple outbound call functionality
- **`sms.py`**: Direct SMS sending with environment validation
- **`scheduler.py`**: Automated call scheduling system that reads from `schedule.json`

### Configuration
- **`schedule.json`**: Call scheduling data with datetime and status tracking
- **`env.sample`**: Complete environment variable template

## Development Patterns

### WebSocket Handling
The AI voice assistant uses WebSocket streaming for real-time audio processing:
- Thread-safe state management for call sessions
- Audio buffer management with configurable chunk sizes
- Barge-in functionality for natural conversation flow

### AI Integration
- Flexible AI provider support (Azure OpenAI vs. standard OpenAI)
- Context-aware conversation handling with GPT-4
- Speech-to-text using Whisper for transcription
- Text-to-speech using Amazon Polly (Joanna voice)

### Error Handling
- Comprehensive environment variable validation
- Structured logging throughout applications
- Graceful handling of API failures and timeouts

### Twilio Webhook Integration
- Flask routes handle incoming voice calls (`/voice`, `/incoming-voice`)
- SMS webhook handling (`/incoming-sms`) with auto-reply logic
- TwiML generation for call flow control

## Testing and Webhooks

### Webhook Endpoints
- **Voice (AI Assistant)**: `https://your-domain/voice`
- **Voice (IVR)**: `https://your-domain/incoming-voice`  
- **SMS**: `https://your-domain/incoming-sms`

### Triggering Outbound Calls
```bash
# AI assistant outbound call
curl -X POST http://localhost:5000/make-call -d "to=+1XXXXXXXXXX"
```

## Key Dependencies

### Core Framework
- **Flask 3.1.1**: Web framework for webhook handling
- **Twilio 9.6.3**: Voice, SMS, and WebSocket communication
- **flask-sockets + gevent**: WebSocket support for real-time streaming

### AI/ML Stack
- **OpenAI 1.93.0**: GPT-4 conversations and Whisper transcription
- **neo4j 5.28.1**: Knowledge graph database
- **graphiti-core 0.14.0**: Advanced graph-based AI processing

## Call Scheduling

The scheduler (`app/scheduler.py`) runs continuously and checks `schedule.json` every 30 seconds for pending calls. Schedule format:

```json
{
  "calls": [
    {
      "to": "+91XXXXXXXXXX",
      "from": "+1TwilioNumber", 
      "message": "Your appointment is scheduled at 5PM.",
      "datetime": "2025-06-26 17:00",
      "called": false
    }
  ]
}
```

## AI Conversation Features

- **Barge-in capability**: Users can interrupt the AI mid-sentence
- **Natural disconnection**: Recognizes phrases like "end the call", "goodbye", "hang up"
- **Context awareness**: Maintains conversation context throughout the call
- **Real-time processing**: Live audio streaming and immediate response generation