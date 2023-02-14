import os

from aws_lambda_powertools import Logger
from boto3 import resource
from telegram import Bot
import requests

from aws.translate import translate_text
from decorators import handle_errors
from aws import dynamodb as dynamodb_operations

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))

API_NINJAS_API_KEY = os.getenv("API_NINJAS_API_KEY")
GET_RANDOM_WORD_URL = "https://api.api-ninjas.com/v1/randomword"
SUGGESTION_TEMPLATE = "Hi. I have a new word for you: {english_text} - {native_text}. Do you want to add it to your vocabulary and start learning it?"
SUGGESTION_OPTIONS = ["Yes, thanks", "No, thanks"]


@handle_errors
def handler(_, __):
    if not API_NINJAS_API_KEY:
        logger.error("API_NINJAS_API_KEY is not found in env variables.")
        return

    response = requests.get(GET_RANDOM_WORD_URL, headers={"X-Api-Key": API_NINJAS_API_KEY})
    if not response.ok:
        logger.error(response.text)
        response.raise_for_status()

    new_word = response.json()["word"].capitalize()
    new_word_translation = translate_text(new_word)
    suggestion_text = SUGGESTION_TEMPLATE.format(english_text=new_word, native_text=new_word_translation)
    for user in dynamodb_operations.list_users():
        user_chat_id = str(user["user_chat_id"])
        poll_id = bot.sendPoll(chat_id=user_chat_id, question=suggestion_text, options=SUGGESTION_OPTIONS,)[
            "poll"
        ]["id"]
        dynamodb_operations.create_suggestion(user_chat_id, poll_id, new_word, new_word_translation)

    return
