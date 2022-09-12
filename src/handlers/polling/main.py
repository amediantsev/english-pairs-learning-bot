import os
import random
from http import HTTPStatus

import telegram
from aws_lambda_powertools import Logger
from boto3 import resource
from telegram import Bot

from decorators import handle_errors
from aws.dynamodb import list_translation_pairs, create_poll, increment_translation_pair_fields
from helpers import sort_pairs_by_priority

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


def select_pair_to_poll(translation_pairs):
    return random.choice(sort_pairs_by_priority(translation_pairs)[:5])


def gather_options(translation_pairs, correct_option, answers_key) -> list:
    options = {correct_option}
    pairs_count = len(translation_pairs)
    options_limit = pairs_count if pairs_count < 4 else 4
    while len(options) < options_limit:
        options.add(random.choice(translation_pairs)[answers_key])

    return list(options)


@handle_errors
def handler(event, _):
    user_chat_id = event["user_chat_id"]
    translation_pairs = list_translation_pairs(user_chat_id)

    question_key, answers_key = "english_text", "native_text"
    if random.choice([True, False]):
        question_key, answers_key = answers_key, question_key

    pair_to_poll = select_pair_to_poll(translation_pairs)
    correct_option = pair_to_poll[answers_key]
    options = gather_options(translation_pairs, correct_option, answers_key)

    poll_id = bot.sendPoll(
        chat_id=user_chat_id,
        question=pair_to_poll[question_key],
        options=options,
        type=telegram.Poll.QUIZ,
        correct_option_id=options.index(correct_option),
    )["poll"]["id"]
    create_poll(user_chat_id, poll_id, pair_to_poll["english_text"])
    increment_translation_pair_fields(user_chat_id, pair_to_poll["english_text"], polls_count=1)

    return {"statusCode": HTTPStatus.OK}
