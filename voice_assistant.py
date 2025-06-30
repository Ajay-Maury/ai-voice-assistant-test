import os
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import OpenAI, AzureOpenAI

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup
app = Flask(__name__)

twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_PHONE_NUMBER")

client = Client(twilio_sid, twilio_token)

# # Create a client instance (will use OPENAI_API_KEY from env)
# openai_client = OpenAI()

# # 🔁 Reusable: get GPT response
# def get_ai_response(user_input):
#     try:
#         response = openai_client.chat.completions.create(
#             model="gpt-4",
#             messages=[
#                 {"role": "system", "content": "You are a helpful voice assistant."},
#                 {"role": "user", "content": user_input}
#             ]
#         )
#         return response.choices[0].message.content.strip()
#     except Exception as e:
#         print("OpenAI Error:", e)
#         return "Sorry, I'm having trouble responding right now."


azure_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv(
        "AZURE_OPENAI_API_VERSION"
    ),  # or whatever version your resource uses
    azure_endpoint=os.getenv(
        "AZURE_OPENAI_ENDPOINT"
    ),  # e.g. https://your-resource.openai.azure.com/
)


def get_ai_response(user_input):
    try:
        response = azure_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),  # not "gpt-4" directly
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful voice assistant, Always respond respectfully.",
                },
                {"role": "user", "content": user_input},
            ],
        )
        print("AI Response:", response.choices[0].message.content.strip())
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("Azure OpenAI Error:", e)
        return "Sorry, something went wrong."


# 🟢 Handle Incoming Calls
@app.route("/voice", methods=["POST"])
def voice():
    vr = VoiceResponse()
    gather = Gather(
        input="speech", action="/ai-response", method="POST", speechTimeout="auto"
    )
    gather.say(
        "Hello, I am your AI assistant. How can I help you today?", voice="Polly.Joanna"
    )
    # gather.say("नमस्ते, मैं आपकी एआई सहायक हूँ। मैं आपकी कैसे मदद कर सकती हूँ?", voice="Polly.Aditi", language="hi-IN")
    vr.append(gather)
    vr.redirect("/voice")  # Repeat prompt if nothing said
    return Response(str(vr), mimetype="text/xml")


# 🤖 Handle AI Responses
@app.route("/ai-response", methods=["POST"])
def ai_response():
    user_input = request.form.get("SpeechResult", "")
    print("User Input:", user_input)

    # 🔍 Check if the user wants to end the call directly
    user_exit_phrases = [
        "end the call",
        "disconnect",
        "hang up",
        "stop talking",
        "goodbye",
        "no thank you",
        # "बस", 
        # "अलविदा", 
        # "धन्यवाद",
        # "कॉल समाप्त",
        # "कोई जरूरत नहीं"
    ]

    if any(phrase in user_input.lower() for phrase in user_exit_phrases):
        vr = VoiceResponse()
        vr.say("You may now hang up the call. Have a great day!", voice="Polly.Joanna")
        # vr.say("आप कॉल समाप्त कर सकते हैं। आपका दिन शुभ हो!", voice="Polly.Aditi", language="hi-IN")
        vr.hangup()
        return Response(str(vr), mimetype="text/xml")

    # 🔁 Otherwise continue to get AI response
    ai_reply = get_ai_response(user_input)
    print("AI Reply:", ai_reply)

    vr = VoiceResponse()
    vr.say(ai_reply, voice="Polly.Joanna")

    # Check if the AI is ending the conversation
    # 🔚 Check if AI wants to end the call
    ai_exit_phrases = [
        "goodbye",
        "end this call",
        "hang up",
        # "अलविदा", 
        # "कॉल समाप्त"
    ]
    if any(phrase in ai_reply.lower() for phrase in ai_exit_phrases):
        vr.say("You may now hang up the call. Have a great day!", voice="Polly.Joanna")
        # vr.say("आप कॉल समाप्त कर सकते हैं। आपका दिन शुभ हो!", voice="Polly.Aditi", language="hi-IN")
        return Response(str(vr), mimetype="text/xml")

    # Continue loop
    gather = Gather(
        input="speech", action="/ai-response", method="POST", speechTimeout="auto"
    )
    gather.say("What else can I help you with?", voice="Polly.Joanna")
    # gather.say("क्या मैं आपकी और कोई मदद कर सकती हूँ?", voice="Polly.Aditi", language="hi-IN")
    vr.append(gather)
    vr.redirect("/voice")
    return Response(str(vr), mimetype="text/xml")


# 🔁 Outgoing Call Trigger
@app.route("/make-call", methods=["POST"])
def make_call():
    print("Received request to make a call")
    to_number = request.form.get("to")

    if not to_number:
        return {"error": "Missing 'to' number"}, 400

    call = client.calls.create(
        url="https://0059-2401-4900-88d0-fb6e-885b-e01-27e8-1c0a.ngrok-free.app/voice",  # change to your public webhook
        to=to_number,
        from_=twilio_number,
    )

    return {"message": "Call initiated", "sid": call.sid}


# 🏁 Run server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
