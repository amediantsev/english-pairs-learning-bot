import json
import os
from http import HTTPStatus
from contextlib import suppress

from aws_lambda_powertools import Logger
from boto3 import client
from telegram import Update

from aws import dynamodb as dynamodb_operations
from aws.events_bridge import put_event, put_targets
from decorators import handle_errors
from exceptions import ProcessMessageError
from helpers import sort_pairs_by_priority
from tg import Chat, bot


ASK_FOR_ENGLISH = "Send me the text of english phrase/word"
ASK_FOR_TRANSLATION = "Send me the translation"
ASK_FOR_RATE = "Send me the rate of how often you want to get polls"
POLLING_LAMBDA_ARN = os.getenv("POLLING_LAMBDA_ARN")

logger = Logger()
lambda_client = client("lambda")


def list_translation_pairs_text(user_chat_id):
    translation_pairs = dynamodb_operations.list_translation_pairs(user_chat_id)
    result_text = f"Count: {len(translation_pairs)}\n\n"
    for pair in sort_pairs_by_priority(translation_pairs):
        pair_line = f"**{pair['english_text']}** - {pair['native_text']}"
        pair_line_length = len(pair_line)
        space_length = 84 - pair_line_length if pair_line_length < 80 else 1
        result_text += f"{pair_line}{' ' * space_length}_(polled {pair.get('polls_count', 0)} times)_\n"

    return result_text


@handle_errors
def handler(event, _):
    logger.info(event)
    update = Update.de_json(json.loads(event.get("body")), bot)
    if poll := update.poll:
        dynamodb_operations.update_poll(
            poll.id,
            answered=True,
            answered_correctly=bool(poll.options[poll.correct_option_id]["voter_count"]),
        )
        return {"statusCode": HTTPStatus.OK}

    chat = Chat(tg_update_obj=update)
    event["user_chat_id"] = user_chat_id = chat.id
    text = chat.text

    if text.startswith("/add_pair"):
        dynamodb_operations.create_current_action(user_chat_id, "TRANSLATION_PAIR_CREATING")
        chat.send_message(text=ASK_FOR_ENGLISH)
    elif text.startswith("/delete_pair"):
        dynamodb_operations.create_current_action(user_chat_id, "TRANSLATION_PAIR_DELETING")
        chat.send_message(text=f"{ASK_FOR_ENGLISH} from the pair you want to delete")
    elif text.startswith("/list_pairs"):
        chat.send_message(text=list_translation_pairs_text(user_chat_id))
    elif text.startswith("/cancel"):
        if any(dynamodb_operations.delete_current_action(user_chat_id)):
            chat.send_message(text="Operation is canceled")
        else:
            raise ProcessMessageError(message="There is no active operations")
    elif text.startswith("/set_polling_rate"):
        time_units = text.split(" ")[0].split("/set_polling_rate_in_")[-1]
        dynamodb_operations.create_current_action(user_chat_id, "POLLING_RATE_UPDATE", time_units=time_units)
        chat.send_message(text=f"{ASK_FOR_RATE} in {time_units}")
    else:
        # Data from customer for some current operation (action)
        if not (current_action := dynamodb_operations.get_current_action(user_chat_id)):
            return {"statusCode": HTTPStatus.OK}

        current_action_type = current_action["action_type"]
        if current_action_type == "TRANSLATION_PAIR_CREATING":
            if english_text := current_action.get("english_text"):
                dynamodb_operations.create_translation_pair(user_chat_id, english_text, native_text=text)
                chat.send_message(text="New translation pair is added")
            else:
                dynamodb_operations.update_current_action(user_chat_id, english_text=text)
                chat.send_message(text=ASK_FOR_TRANSLATION)
        elif current_action_type == "TRANSLATION_PAIR_DELETING":
            if dynamodb_operations.delete_translation_pair(user_chat_id, text):
                chat.send_message(text="Translation pair is deleted")
            else:
                raise ProcessMessageError(
                    message=(
                        "There is no pair with such english phrase. Please, try again or cancel the operation (/cancel)"
                    )
                )
        elif current_action_type == "POLLING_RATE_UPDATE":
            time_units = current_action["time_units"]
            time_amount = text
            if not time_amount or not time_amount.isdigit():
                raise ProcessMessageError(
                    message="Specified rate is incorrect. Please, try again or cancel the operation (/cancel)"
                )
            if time_amount == "1":
                # Remove 's'
                time_units = time_units[:-1]
            rule_name = f"{user_chat_id}_POLLING"
            rule_arn = put_event(rule_name, f"rate({time_amount} {time_units})")
            put_targets(
                rule_name,
                [
                    {
                        "Arn": POLLING_LAMBDA_ARN,
                        "Id": "POLLING_LAMBDA",
                        "Input": json.dumps({"user_chat_id": user_chat_id}),
                    }
                ],
            )
            with suppress(lambda_client.exceptions.ResourceConflictException):
                lambda_client.add_permission(
                    FunctionName=POLLING_LAMBDA_ARN,
                    StatementId=f"PERIODIC_{user_chat_id}_POLLING_PERMISSION",
                    Action="lambda:InvokeFunction",
                    Principal="events.amazonaws.com",
                    SourceArn=rule_arn,
                )
            dynamodb_operations.delete_current_action(user_chat_id)
            chat.send_message(text=f"Okay, I will poll you every {time_amount} {time_units}")

    return {"statusCode": HTTPStatus.OK}
