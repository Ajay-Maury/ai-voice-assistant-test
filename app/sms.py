from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()
client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

if not client:
    raise ValueError("Twilio client could not be initialized. Check your credentials.")
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')

if not twilio_phone_number:
    raise ValueError("TWILIO_PHONE_NUMBER environment variable is not set.")

verified_test_number = os.getenv('VERIFIED_TEST_NUMBER')
if not verified_test_number:
    raise ValueError("VERIFIED_TEST_NUMBER environment variable is not set.")

message = client.messages.create(
    body="Hi! This is a test SMS.",
    from_=twilio_phone_number,
    to=verified_test_number
)

print("Message SID:", message.sid)
