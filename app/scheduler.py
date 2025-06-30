import json
import time
from datetime import datetime
from twilio.rest import Client
import os
from dotenv import load_dotenv
import logging
import pytz

# Setup logging
logging.basicConfig(
    filename='scheduler.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Load environment variables
load_dotenv()
client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

def call_user(call):
    try:
        response = client.calls.create(
            twiml=f'<Response><Say>{call["message"]}</Say></Response>',
            to=call["to"],
            from_=call["from"]
        )
        logging.info(f"Call initiated to {call['to']} with SID {response.sid}")
    except Exception as e:
        logging.error(f"Failed to call {call['to']}: {e}")

def check_and_call():
    try:
        with open('schedule.json', 'r') as f:
            data = json.load(f)

        now = datetime.now(IST).strftime('%Y-%m-%d %H:%M')
        logging.info(f"Checking scheduled calls at {now} IST")

        for call in data["calls"]:
            if call["datetime"] == now and not call.get("called", False):
                call_user(call)
                call["called"] = True

        with open('schedule.json', 'w') as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        logging.error(f"Error in check_and_call: {e}")

if __name__ == "__main__":
    logging.info("📞 Scheduler started. Checking every 30 seconds.")
    while True:
        check_and_call()
        time.sleep(30)
