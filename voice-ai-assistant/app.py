import os
from flask import Flask, request, Response, jsonify
from twilio.twiml.voice_response import VoiceResponse, Start, Stream, Connect
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Twilio setup
twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
client = Client(twilio_sid, twilio_token)

@app.route("/voice", methods=["POST"])
def voice():
    call_sid = request.form.get("CallSid")
    print(f"Received CallSid: {call_sid}")
    if not call_sid:
        return jsonify({"error": "Missing CallSid"}), 400

    response = VoiceResponse()
    connect = Connect()
    print("Connecting to WebSocket...")
    
    connect.stream(
        url="wss://mentioned-spam-dee-jazz.trycloudflare.com/ws"
    )
    response.append(connect)
    response.pause(length=60)  # keeps stream alive for 60s

    return Response(str(response), mimetype="text/xml")


@app.route("/wait", methods=["POST"])
def wait():
    vr = VoiceResponse()
    vr.pause(length=60)  # keeps stream alive for 60s
    vr.redirect("/wait")  # loop to keep call open
    return Response(str(vr), mimetype="text/xml")


@app.route("/make-call", methods=["POST"])
def make_call():
    to_number = request.form.get("to")
    if not to_number:
        return jsonify({"error": "Missing 'to' number"}), 400

    call = client.calls.create(
        to=to_number,
        from_=twilio_number ,
        url="https://0ea0-2401-4900-88d0-fb6e-885b-e01-27e8-1c0a.ngrok-free.app/voice"
    )
    return jsonify({"message": "Call initiated", "sid": call.sid})

if __name__ == "__main__":
    app.run(debug=True, port=5000)