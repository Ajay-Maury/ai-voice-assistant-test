# 📞 Twilio KT (Knowledge Transfer) – India-Focused Integration

This repo demonstrates end-to-end usage of **Twilio** for:

- ✅ Voice Calls (Incoming & Outgoing)
- ✅ Interactive Voice Response (IVR) – Press 1 / Press 2
- ✅ SMS Sending & Auto-Reply
- ✅ WhatsApp Messaging
- ✅ Email Sending (via SendGrid)
- ✅ Scheduled Call Automation

---

## 🛠️ Setup Instructions

1. **Clone the repo**
   ```bash
   git clone https://github.com/yourusername/twilio-kt.git
   cd twilio-kt
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.sample .env
   # Fill in your Twilio and SendGrid credentials
   ```

---

## 🔧 Environment Variables

In your `.env` file:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
WHATSAPP_SANDBOX_NUMBER=whatsapp:+14155238886
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxx
```

---

## 🚀 Project Structure

```
twilio-kt/
├── app/
│   ├── voice_outgoing.py       # Make an outbound call
│   ├── sms.py                  # Send SMS
│   ├── scheduler.py            # Check JSON schedule and make calls
│   └── email_sendgrid.py       # Send email (optional)
├── server.py                   # Handles incoming voice/SMS/IVR
├── schedule.json               # Call schedule storage
├── requirements.txt
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

### ✅ 2. Incoming Call with IVR (Press 1, Press 2)

Run:
```bash
python server.py
```

- Set webhook on your Twilio console for **Voice** to:
  ```
  https://your-ngrok-or-server/incoming-voice
  ```

- Logic:
  - Press 1 → Connects to Sales
  - Press 2 → Connects to Support

---

## 📩 SMS Functionality

### ✅ Send SMS
```bash
python app/sms.py
```

### ✅ Auto-Reply to SMS

Set Twilio SMS webhook to:
```
https://your-ngrok-or-server/incoming-sms
```

- Replies to:
  - "hi" → "Hello!"
  - "1" → Account help
  - "2" → Support

---

## 🟢 WhatsApp Support (Optional)

Same as SMS logic; just update the number with:
```
from_='whatsapp:+14155238886',
to='whatsapp:+91XXXXXXXXXX'
```

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

## 📧 Send Email (SendGrid)

Create `email_sendgrid.py` like:

```python
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os

message = Mail(
    from_email='your@example.com',
    to_emails='to@example.com',
    subject='Appointment Reminder',
    plain_text_content='This is a test email from Twilio KT project.'
)

sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
response = sg.send(message)
print(response.status_code)
```

---

## 🧪 Testing Tips

- Use [ngrok](https://ngrok.com/) to test webhooks:
  ```bash
  ngrok http 5000
  ```

- Set this ngrok URL in Twilio Console for:
  - Voice: `/incoming-voice`
  - SMS: `/incoming-sms`

---

## 📌 Common Use Cases (Mapped)

| Feature         | Tool/File               | How to Use                      |
|------------------|--------------------------|----------------------------------|
| Outgoing Call    | `voice_outgoing.py`      | Run directly via Python         |
| Incoming Call    | `server.py`              | Webhook with IVR                |
| Press 1 / 2 IVR  | `/incoming-voice` route  | Uses TwiML Gather               |
| Send SMS         | `sms.py`                 | Uses Twilio `messages.create`   |
| Receive SMS      | `/incoming-sms`          | Auto-response with Flask        |
| WhatsApp         | Use `whatsapp:` numbers  | Similar to SMS                  |
| Email            | SendGrid API             | Optional email alerts           |
| Scheduler        | `scheduler.py` + JSON    | Reads schedule every minute     |

---

## 👨‍💻 Author

Made with ❤️ for KT Sessions  
📍 Focused on India Twilio integrations  
🌐 [OpenAI Developer Tools](https://platform.openai.com/)
