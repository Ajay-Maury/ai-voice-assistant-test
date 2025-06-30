from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.twiml.messaging_response import MessagingResponse
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

verified_test_number = os.getenv('VERIFIED_TEST_NUMBER')
if not verified_test_number:
    raise ValueError("VERIFIED_TEST_NUMBER environment variable is not set.")

@app.route("/voice", methods=["POST"])
def incoming_voice():
    resp = VoiceResponse()
    gather = Gather(num_digits=1, action="/handle-key", method="POST")
    gather.say("Welcome! Press 1 for Sales, 2 for Support.")
    resp.append(gather)
    resp.redirect("/incoming-voice")
    return str(resp)

@app.route("/handle-key", methods=["POST"])
def handle_key():
    digit = request.form.get("Digits")
    print("Received digit:", digit)
    resp = VoiceResponse()
    if digit == "1":
        resp.say("Connecting to Sales.")
        resp.dial(verified_test_number)
    elif digit == "2":
        resp.say("Connecting to Support.")
        resp.dial(verified_test_number)
    else:
        resp.say("Invalid choice.")
        resp.redirect("/incoming-voice")
    return str(resp)

@app.route("/incoming-sms", methods=["POST"])
def incoming_sms():
    body = request.form.get("Body", "").lower()
    print("Received SMS:", body)
    resp = MessagingResponse()
    if "hi" in body:
        resp.message("Hello! How can I help?")
    elif body.strip() == "1":
        resp.message("You chose Account.")
    elif body.strip() == "2":
        resp.message("You chose Support.")
    else:
        resp.message("Reply HELP for options: 1.Account 2.Support")
    print("Response SMS:", resp.message)
    return str(resp)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
