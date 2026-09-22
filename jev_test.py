import os

from dotenv import load_dotenv
from typesafe_sdk import Noul, TypeSafeClient

load_dotenv()

client = TypeSafeClient(
    api_key=os.environ["TYPESAFE_API_KEY"]
)

result = client.system_one(
    state={
        "message": "Can you send me your availability and rates for a product design project?"
    },
    questions={
        "is_business_lead": Noul(
            instructions="Is this message a potential business lead or project inquiry?"
        )
    },
)

print(result)
