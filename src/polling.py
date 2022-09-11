import os
import random
from http import HTTPStatus

import telegram
from aws_lambda_powertools import Logger
from boto3 import resource
from telegram import Bot

from messages import list_translation_pairs


logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


@logger.inject_lambda_context(log_event=True)
def handler(event, _):
    user_chat_id = event["user_chat_id"]
    query_result = list_translation_pairs(user_chat_id)
    translation_pairs = query_result["Items"]
    pairs_count = query_result["Count"]

    pair_to_poll = random.choice(translation_pairs)
    correct_option = pair_to_poll["native_text"]
    options = {correct_option}
    options_limit = pairs_count if pairs_count < 4 else 4
    while len(options) < options_limit:
        options.add(random.choice(translation_pairs)["native_text"])

    options = list(options)
    bot.sendPoll(
        chat_id=user_chat_id,
        question=pair_to_poll["english_text"],
        options=options,
        type=telegram.Poll.QUIZ,
        correct_option_id=options.index(correct_option),
    )

    return {"statusCode": HTTPStatus.OK}
