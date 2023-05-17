import os
from concurrent.futures import ThreadPoolExecutor

from aws_lambda_powertools import Logger
from boto3 import resource
from telegram import Bot

from aws.dynamodb import list_translation_pairs
from decorators import handle_errors
from aws import dynamodb as dynamodb_operations
from exceptions import GptResponseFormatError
from gpt import suggest_new_pairs, OPENAI_API_KEY

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))

SUGGESTION_TEXT = (
    "Привіт. У мене є кілька нових слів для тебе.\n"
    "Можеш вибрати ті, які хотілось би вивчити, і я додам їх до твого словнику."
)


def send_suggestion(user_chat_id, new_translations):
    poll_id = bot.sendPoll(
        chat_id=user_chat_id,
        question=SUGGESTION_TEXT,
        options=[f"{word} - {translation}" for word, translation in new_translations],
        allows_multiple_answers=True,
    )["poll"]["id"]
    dynamodb_operations.create_suggestion(user_chat_id, poll_id, new_translations)


def generate_and_send_suggestion(user_chat_id, existing_pairs):
    try:
        new_translations = suggest_new_pairs(existing_pairs)
    except GptResponseFormatError:
        logger.exception("GPT response format error")
        return
    logger.info({"user_chat_id": user_chat_id, "new_translations": new_translations})
    send_suggestion(user_chat_id, new_translations)


@handle_errors
def handler(_, __):
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set")
        return

    with ThreadPoolExecutor() as executor:
        for user in dynamodb_operations.list_users():
            user_chat_id = str(user["user_chat_id"])
            logger.info("Making Suggestion for user ", user_chat_id)
            if not (existing_pairs := list_translation_pairs(user_chat_id)):
                logger.info("No existing pairs for user ", user_chat_id)
                continue
            executor.submit(generate_and_send_suggestion, user_chat_id, existing_pairs)

    return
