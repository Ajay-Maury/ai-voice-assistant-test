
# 📞 Twilio AI Voice Assistant Prototype

This repo demonstrates end-to-end usage of **Twilio** for:

- ✅ Voice Calls (Incoming & Outgoing)
- ✅ Interactive Voice Response (IVR) – Press 1 / Press 2
- ✅ SMS Sending & Auto-Reply
- ✅ Scheduled Call Automation
- ✅ Voice Calls (Incoming & Outgoing) with AI Assistant

---

## 🛠️ Setup Instructions

1. **Clone the repo**
   ```bash
   git clone https://github.com/yourusername/twilio-kt.git
   cd twilio-kt
   ````

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**

   ```bash
   cp .env.sample .env
   # Fill in your Twilio and Azure OpenAI credentials
   ```

---

## 🔧 Environment Variables

In your `.env` file:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX

# For AI Voice Assistant
AZURE_OPENAI_API_KEY=your_azure_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2023-05-15
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4-deployment-name
```

---

## 🚀 Project Structure

```
twilio-kt/
├── app/
│   ├── voice_outgoing.py       # Make an outbound call
│   ├── sms.py                  # Send SMS
│   ├── scheduler.py            # Check JSON schedule and make calls
├── server.py                   # Handles incoming voice/SMS/IVR
├── schedule.json               # Call schedule storage
├── requirements.txt
├── voice_assistant.py          # Handles incoming/outgoing calls with AI Assistant
├── .env.sample
└── README.md
```

---

## 📞 Voice Call Features

### ✅ 1. Outgoing Call

```bash
python app/voice_outgoing.py
```

> Sends a voice call to the recipient using Twilio's Say command.

---

### ✅ 2. Incoming Call with IVR (Press 1, Press 2)

Run:

```bash
python server.py
```

* Set webhook on your Twilio console for **Voice** to:

  ```
  https://your-ngrok-or-server/incoming-voice
  ```

* Logic:

  * Press 1 → Connects to Sales
  * Press 2 → Connects to Support

---

## 📩 SMS Functionality

### ✅ Send SMS

```bash
python app/sms.py
```

---

### ✅ Auto-Reply to SMS

Set Twilio SMS webhook to:

```
https://your-ngrok-or-server/incoming-sms
```

* Replies to:

  * "hi" → "Hello!"
  * "1" → Account help
  * "2" → Support

---

## 🕒 Scheduled Call Automation

Edit `schedule.json`:

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

Then run:

```bash
python app/scheduler.py
```

> Every minute, it checks if the current time matches a scheduled call and initiates it.

---

## 🤖 Incoming/Outgoing Calls with AI Assistant

This feature enables dynamic conversations between callers and an AI-powered assistant using **Azure OpenAI GPT-4** and **Twilio Voice**.

---

### ✅ Incoming Call (AI Assistant)

1. **Run the AI voice server**:

   ```bash
   python voice_assistant.py
   ```

2. **Set Twilio Voice Webhook**:

   * Go to [Twilio Console > Phone Numbers](https://www.twilio.com/console/phone-numbers)
   * Under **Voice & Fax**, set the webhook URL:

     ```
     https://your-ngrok-or-server/voice
     Method: POST
     ```

3. **Behavior**:

   * Greets the caller: “Hello, I am your AI assistant. How can I help you today?”
   * Captures user speech and sends it to Azure OpenAI GPT-4.
   * Responds using a natural voice (`Polly.Joanna`).
   * User can say “end the call” or “goodbye” to disconnect.

---

### ✅ Outgoing Call (AI Assistant)

Make a POST request to trigger an AI-driven call:

```bash
curl -X POST http://localhost:5000/make-call \
  -d "to=+1XXXXXXXXXX"
```

> The recipient will receive a call and interact with the AI assistant similarly to an inbound call.

---

### 🧠 Key Features

* **Speech recognition + Twilio Gather** for input
* **GPT-4 (via Azure OpenAI)** for context-aware replies
* **Amazon Polly voice (Joanna)** for lifelike responses
* **Natural disconnection flow**: recognizes exit phrases like:

  * "end the call"
  * "hang up"
  * "goodbye"
  * "no thank you"

---

## 🧪 Testing Tips

* Use [ngrok](https://ngrok.com/) to test webhooks:

  ```bash
  ngrok http 5000
  ```

* Set this ngrok URL in Twilio Console for:

  * Voice: `/incoming-voice` or `/voice` (for AI Assistant)
  * SMS: `/incoming-sms`

---

## 📌 Common Use Cases (Mapped)

| Feature         | Tool/File               | How to Use                      |
| --------------- | ----------------------- | ------------------------------- |
| Outgoing Call   | `voice_outgoing.py`     | Run directly via Python         |
| Incoming Call   | `server.py`             | Webhook with IVR                |
| Press 1 / 2 IVR | `/incoming-voice` route | Uses TwiML Gather               |
| Send SMS        | `sms.py`                | Uses Twilio `messages.create`   |
| Receive SMS     | `/incoming-sms`         | Auto-response with Flask        |
| Scheduler       | `scheduler.py` + JSON   | Reads schedule every minute     |
| Voice Assistant | `voice_assistant.py`    | AI-powered voice assistant flow |

---
