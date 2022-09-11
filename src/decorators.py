import os
from http import HTTPStatus

from aws_lambda_powertools import Logger
from telegram import Bot

from exceptions import ProcessMessageError


logger = Logger()
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


def handle_errors(f):
    def wrapper(event, context):
        try:
            return f(event, context)
        except ProcessMessageError as e:
            if e.message and (user_chat_id := event.get("user_chat_id")):
                bot.sendMessage(chat_id=user_chat_id, text=e.message)
        except Exception:
            logger.exception("Unexpected error.")
            if user_chat_id := event.get("user_chat_id"):
                bot.sendMessage(chat_id=user_chat_id, text="Sorry, something went wrong")

        return {"statusCode": HTTPStatus.OK}

    return wrapper
