import logging
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

WEB_SOCKET_URL="wss://3nhvvprj-8765.inc1.devtunnels.ms/ws"
VOICE_ROUTE_URL="https://3nhvvprj-5001.inc1.devtunnels.ms/voice"

app = Flask(__name__)

# Twilio setup
client = Client(TWILIO_SID, TWILIO_TOKEN)


@app.route("/", methods=["GET", "POST"])
def health_check():
    return jsonify({"message": "Welcome to AI voice assistant service"})


@app.route("/voice", methods=["POST"])
def voice():
    try:
        call_sid = request.form.get("CallSid")
        if not call_sid:
            logging.warning("Missing CallSid in request")
            return jsonify({"error": "Missing CallSid"}), 400

        logging.info(f"Received CallSid: {call_sid}")
        response = VoiceResponse()
        connect = Connect()

        logging.info(f"Connecting to WebSocket at {WEB_SOCKET_URL}...")
        connect.stream(url=WEB_SOCKET_URL)
        response.append(connect)

        # Keep the stream open (adjust based on your use case)
        response.pause(length=60)

        return Response(str(response), mimetype="text/xml")

    except Exception as e:
        logging.exception("Error handling /voice request")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

@app.route("/make-call", methods=["POST"])
def make_call():
    try:
        to_number = request.form.get("to")
        if not to_number:
            logging.warning("Missing 'to' number in request")
            return jsonify({"error": "Missing 'to' number"}), 400

        if not TWILIO_NUMBER or not VOICE_ROUTE_URL:
            logging.error("TWILIO_NUMBER or VOICE_ROUTE_URL is not set")
            return jsonify({"error": "Server misconfiguration"}), 500

        logging.info(f"Initiating call from {TWILIO_NUMBER} to {to_number}")
        call = client.calls.create(
            to=to_number,
            from_=TWILIO_NUMBER,
            url=VOICE_ROUTE_URL,
        )

        return jsonify({"message": "Call initiated", "sid": call.sid})

    except Exception as e:
        logging.exception("Error initiating call")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, host="0.0.0.0", port=5001)
