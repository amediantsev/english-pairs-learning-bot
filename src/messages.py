import json
import os
from http import HTTPStatus
from contextlib import suppress

from aws_lambda_powertools import Logger
from boto3 import resource, client
from boto3.dynamodb.conditions import Key
from telegram import Update, Bot

from decorators import handle_errors
from exceptions import ProcessMessageError

ASK_FOR_ENGLISH = "Send me the text of english phrase/word"
ASK_FOR_TRANSLATION = "Send me the translation"
ASK_FOR_RATE = "Send me the rate of how often you want to get polls"
POLLING_LAMBDA_ARN = os.getenv("POLLING_LAMBDA_ARN")

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))
events_client = client("events")
lambda_client = client("lambda")

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


def create_current_action(user_chat_id, action_type, **kwargs):
    if get_current_action(user_chat_id):
        raise ProcessMessageError(message="Please, finish current operation or cancel it (/cancel)")
    table.put_item(
        Item={
            "pk": f"USER#{user_chat_id}",
            "sk": "CURRENT_ACTION",
            "user_id": user_chat_id,
            "action_type": action_type,
            **kwargs,
        }
    )


def update_current_action(user_chat_id, **kwargs):
    table.update_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": "CURRENT_ACTION"},
        AttributeUpdates={k: {"Value": v, "Action": "PUT"} for k, v in kwargs.items()},
    )


def get_current_action(user_chat_id):
    return table.get_item(Key=({"pk": f"USER#{user_chat_id}", "sk": "CURRENT_ACTION"})).get("Item")


def delete_current_action(user_chat_id):
    return table.delete_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": "CURRENT_ACTION"}, ReturnValues="ALL_OLD"
    ).get("Attributes")


def create_translation_pair(user_chat_id, english_text, native_text):
    table.put_item(
        Item={
            "pk": f"USER#{user_chat_id}",
            "sk": f"TRANSLATION_PAIR#{english_text}",
            "user_id": user_chat_id,
            "english_text": english_text,
            "native_text": native_text,
        }
    )
    delete_current_action(user_chat_id)


def delete_translation_pair(user_chat_id, english_text):
    deleted_pair = table.delete_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": f"TRANSLATION_PAIR#{english_text}"}, ReturnValues="ALL_OLD"
    ).get("Attributes")
    if deleted_pair:
        delete_current_action(user_chat_id)
    return deleted_pair


def list_translation_pairs(user_chat_id):
    return table.query(
        KeyConditionExpression=(Key("pk").eq(f"USER#{user_chat_id}") & Key("sk").begins_with("TRANSLATION_PAIR#"))
    )


def list_translation_pairs_text(user_chat_id):
    query_result = list_translation_pairs(user_chat_id)
    result_text = f"Count: {query_result['Count']}\n\n"
    for pair in query_result["Items"]:
        result_text += f"{pair['english_text']} - {pair['native_text']}\n"

    return result_text


@handle_errors
def handler(event, _):
    update = Update.de_json(json.loads(event.get("body")), bot)

    user_chat_id = update.message.chat.id
    event["user_chat_id"] = user_chat_id
    text = update.message.text

    if text.startswith("/add_pair"):
        create_current_action(user_chat_id, "TRANSLATION_PAIR_CREATING")
        bot.sendMessage(chat_id=user_chat_id, text=ASK_FOR_ENGLISH)
    elif text.startswith("/delete_pair"):
        create_current_action(user_chat_id, "TRANSLATION_PAIR_DELETING")
        bot.sendMessage(chat_id=user_chat_id, text=f"{ASK_FOR_ENGLISH} from the pair you want to delete")
    elif text.startswith("/list_pairs"):
        bot.sendMessage(chat_id=user_chat_id, text=list_translation_pairs_text(user_chat_id))
    elif text.startswith("/cancel"):
        if any(delete_current_action(user_chat_id)):
            bot.sendMessage(chat_id=user_chat_id, text="Operation is canceled")
        else:
            raise ProcessMessageError(message="There is no active operations")
    elif text.startswith("/set_polling_rate"):
        time_units = text.split(" ")[0].split("/set_polling_rate_in_")[-1]
        create_current_action(user_chat_id, "POLLING_RATE_UPDATE", time_units=time_units)
        bot.sendMessage(chat_id=user_chat_id, text=f"{ASK_FOR_RATE} in {time_units}")
    else:
        # Data from customer for some current operation (action)
        if not (current_action := get_current_action(user_chat_id)):
            return {"statusCode": HTTPStatus.OK}

        current_action_type = current_action["action_type"]
        if current_action_type == "TRANSLATION_PAIR_CREATING":
            if english_text := current_action.get("english_text"):
                create_translation_pair(user_chat_id, english_text, native_text=text)
                bot.sendMessage(chat_id=user_chat_id, text="New translation pair is added")
            else:
                update_current_action(user_chat_id, english_text=text)
                bot.sendMessage(chat_id=user_chat_id, text=ASK_FOR_TRANSLATION)
        elif current_action_type == "TRANSLATION_PAIR_DELETING":
            if delete_translation_pair(user_chat_id, text):
                bot.sendMessage(chat_id=user_chat_id, text="Translation pair is deleted")
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
            rule_arn = events_client.put_rule(
                Name=rule_name,
                ScheduleExpression=f"rate({time_amount} {time_units})",
                State="ENABLED",
            )["RuleArn"]
            events_client.put_targets(
                Rule=rule_name,
                Targets=[
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
            delete_current_action(user_chat_id)
            bot.sendMessage(chat_id=user_chat_id, text=f"Okay, I will poll you every {time_amount} {time_units}")

    return {"statusCode": HTTPStatus.OK}
