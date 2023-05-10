import os

from aws_lambda_powertools import Logger
from boto3 import resource
from telegram import Bot

from aws.dynamodb import list_translation_pairs
from decorators import handle_errors
from aws import dynamodb as dynamodb_operations
from gpt import suggest_new_pairs, OPENAI_API_KEY

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))

SUGGESTION_TEXT = "Hi. I have a few new words for you. You can select the ones you would like to learn and I will add it to your vocabulary."

SUGGESTION_OPTIONS = ["Yes, thanks", "No, thanks"]


@handle_errors
def handler(_, __):
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set")
        return

    for user in dynamodb_operations.list_users():
        user_chat_id = str(user["user_chat_id"])
        new_translations = suggest_new_pairs(list_translation_pairs(user_chat_id, limit=20))
        poll_id = bot.sendPoll(
            chat_id=user_chat_id,
            question=SUGGESTION_TEXT,
            options=[f"{word} - {translation}" for word, translation in new_translations],
            allows_multiple_answers=True,
        )["poll"]["id"]
        dynamodb_operations.create_suggestion(user_chat_id, poll_id, new_translations)

    return
