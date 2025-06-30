from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()
client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')

verified_test_number = os.getenv('VERIFIED_TEST_NUMBER')
if not verified_test_number:
    raise ValueError("VERIFIED_TEST_NUMBER environment variable is not set.")

if not client:
    raise ValueError("Twilio client could not be initialized. Check your credentials.")

if not twilio_phone_number:
    raise ValueError("TWILIO_PHONE_NUMBER environment variable is not set.")

call = client.calls.create(
    twiml='<Response><Say>This is a test call from Twilio India.</Say></Response>',
    to=verified_test_number,
    from_=twilio_phone_number
)

print("Call SID:", call.sid)
