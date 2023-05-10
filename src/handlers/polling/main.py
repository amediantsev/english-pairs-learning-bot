import os
import random
from datetime import datetime
from http import HTTPStatus

import telegram
from aws_lambda_powertools import Logger
from boto3 import resource
from telegram import Bot

from decorators import handle_errors
from aws import dynamodb as dynamodb_operations
from helpers import sort_pairs_by_priority
from tg import send_message

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))

POOL_SIZES_DISTRIBUTION = (
    *(5 for _ in range(7)),
    *(8 for _ in range(6)),
    *(12 for _ in range(5)),
    *(15 for _ in range(4)),
    *(20 for _ in range(3)),
    *(25 for _ in range(3)),
    *(30 for _ in range(1)),
)
BOOLEANS = (True, False)


def select_pair_to_poll(translation_pairs):
    pool_size = random.choice(POOL_SIZES_DISTRIBUTION)
    return random.choice(sort_pairs_by_priority(translation_pairs)[:pool_size])


def gather_options(translation_pairs, correct_option, answers_key) -> list:
    options = {correct_option}
    pairs_count = len(translation_pairs)
    options_limit = pairs_count if pairs_count < 4 else 4
    while len(options) < options_limit:
        options.add(random.choice(translation_pairs)[answers_key])

    return list(options)


@handle_errors
def handler(event, _):
    if 22 < datetime.now().hour or datetime.now().hour < 7:
        # We don't bother users at night
        return {"statusCode": HTTPStatus.OK}

    user_chat_id = event["user_chat_id"]
    translation_pairs = dynamodb_operations.list_translation_pairs(user_chat_id)
    translation_pairs_number = len(translation_pairs)
    if translation_pairs_number < 2:
        send_message(
            user_chat_id=user_chat_id,
            text=(
                "Я намагався надіслати тобі опитування, але у тебе недостатньо пар перекладу.\n"
                f"Поточна кількість - {translation_pairs_number}, потрібно - 2 або більше. "
                r"Будь ласка, додай кілька слів/фраз за допомогою команди /add\_pair"
            ),
        )
        return {"statusCode": HTTPStatus.OK}

    question_key, answers_key = "english_text", "native_text"
    if random.choice(BOOLEANS):
        question_key, answers_key = answers_key, question_key

    pair_to_poll = select_pair_to_poll(translation_pairs)

    question = pair_to_poll[question_key]
    answer = pair_to_poll[answers_key]

    if random.random() < 0.2:
        # Open translation question.
        current_action = dynamodb_operations.get_current_action(user_chat_id)
        if current_action and current_action["action_type"] == "OPEN_QUESTION":
            send_message(
                user_chat_id=user_chat_id,
                text=f"Reminder: Send me the translation for _'{current_action['question']}'_",
            )
            return {"statusCode": HTTPStatus.OK}

        dynamodb_operations.create_current_action(
            user_chat_id,
            "OPEN_QUESTION",
            question=question,
            answer=answer,
            english_text=pair_to_poll["english_text"],
        )
        send_message(user_chat_id=user_chat_id, text=f"Send me the translation for _'{question}'_")
        return {"statusCode": HTTPStatus.OK}

    options = gather_options(translation_pairs, answer, answers_key)

    poll_id = bot.sendPoll(
        chat_id=user_chat_id,
        question=question,
        options=options,
        type=telegram.Poll.QUIZ,
        correct_option_id=options.index(answer),
    )["poll"]["id"]
    dynamodb_operations.create_poll(user_chat_id, poll_id, pair_to_poll["english_text"])
    dynamodb_operations.increment_translation_pair_fields(user_chat_id, pair_to_poll["english_text"], polls_count=1)

    return {"statusCode": HTTPStatus.OK}
