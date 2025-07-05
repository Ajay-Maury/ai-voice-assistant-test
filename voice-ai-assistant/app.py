from flask import Flask, request, Response, jsonify
from twilio.twiml.voice_response import VoiceResponse, Start, Stream, Connect
from twilio.rest import Client
from config.settings import (
    TWILIO_SID,
    TWILIO_TOKEN,
    TWILIO_NUMBER,
    # VOICE_ROUTE_URL,
    # WEB_SOCKET_URL,
)

WEB_SOCKET_URL="wss://myvoicews.loca.lt"
VOICE_ROUTE_URL="https://cae4-115-96-179-103.ngrok-free.app/voice"


print("Starting Flask app...")
print("WebSocket URL:", WEB_SOCKET_URL)
print("Voice Route URL:", VOICE_ROUTE_URL)

app = Flask(__name__)

# Twilio setup
client = Client(TWILIO_SID, TWILIO_TOKEN)


@app.route("/voice", methods=["POST"])
def voice():
    call_sid = request.form.get("CallSid")
    print(f"Received CallSid: {call_sid}")
    if not call_sid:
        return jsonify({"error": "Missing CallSid"}), 400

    response = VoiceResponse()
    connect = Connect()
    print(f"Connecting to WebSocket at {WEB_SOCKET_URL}...")

    connect.stream(url=WEB_SOCKET_URL)
    response.append(connect)
    response.pause(length=60)  # keeps stream alive for 60s

    return Response(str(response), mimetype="text/xml")


@app.route("/make-call", methods=["POST"])
def make_call():
    to_number = request.form.get("to")
    if not to_number:
        return jsonify({"error": "Missing 'to' number"}), 400

    call = client.calls.create(
        to=to_number,
        from_=TWILIO_NUMBER,
        url=VOICE_ROUTE_URL,
    )
    return jsonify({"message": "Call initiated", "sid": call.sid})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
