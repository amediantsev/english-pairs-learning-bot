import os
import traceback
from http import HTTPStatus

from aws_lambda_powertools import Logger
from telegram.error import Unauthorized

from exceptions import ProcessMessageError
from tg import ADMIN_IDS, send_message
from users import remove_user
from aws.dynamodb import get_user

logger = Logger()

POLLING_LAMBDA_ARN = os.getenv("POLLING_LAMBDA_ARN")


def handle_errors(f):
    def wrapper(event, context):
        try:
            return f(event, context)
        except ProcessMessageError as e:
            if e.message and (user_chat_id := event.get("user_chat_id")):
                send_message(user_chat_id=user_chat_id, text=e.message)
        except Unauthorized:
            user_chat_id = event.get("user_chat_id")
            if user_chat_id and user_chat_id not in ADMIN_IDS:
                logger.error(f"user {user_chat_id} has blocked bot")
                remove_user(user_chat_id, POLLING_LAMBDA_ARN or context.invoked_function_arn)
        except Exception:
            logger.exception("Unexpected error.")
            if user_chat_id := event.get("user_chat_id"):
                send_message(user_chat_id=user_chat_id, text="Sorry, something went wrong.")

            for admin_id in ADMIN_IDS:
                send_message(
                    user_chat_id=admin_id,
                    text=(
                        f"Error happened for @{get_user(user_chat_id).get('username', user_chat_id)}:"
                        f"\n\n"
                        f"{traceback.format_exc()}"
                    ),
                    disable_markdown=True,
                )

        return {"statusCode": HTTPStatus.OK}

    return wrapper
