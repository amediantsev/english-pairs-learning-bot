import json
import os
from http import HTTPStatus

from aws_lambda_powertools import Logger
from boto3 import resource, client
from boto3.dynamodb.conditions import Key
from telegram import Update, Bot

from decorators import handle_unexpected_error

ASK_FOR_ENGLISH = "Send me the text of english phrase/word"
ASK_FOR_TRANSLATION = "Send me the translation"
POLLING_LAMBDA_ARN = os.getenv("POLLING_LAMBDA_ARN")

logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))
events_client = client("events")
lambda_client = client("lambda")

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


def create_translation_pair(user_chat_id):
    table.put_item(Item={"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_CREATING", "user_id": user_chat_id})


def create_translation_pair_deleting(user_chat_id):
    table.put_item(Item={"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_DELETING", "user_id": user_chat_id})


def add_english_text_to_pair(user_chat_id, english_text):
    table.update_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_CREATING"},
        AttributeUpdates={"english_text": {"Value": english_text, "Action": "PUT"}},
    )


def add_native_text_to_pair(pair_item, native_text):
    table.put_item(
        Item={
            **pair_item,
            "native_text": native_text,
            "sk": f"TRANSLATION_PAIR#{pair_item['english_text']}",
        }
    )
    table.delete_item(Key={"pk": pair_item["pk"], "sk": pair_item["sk"]})


def delete_translation_pair(pair_deleting_item, english_text):
    deleted_pair = table.delete_item(
        Key={"pk": pair_deleting_item["pk"], "sk": f"TRANSLATION_PAIR#{english_text}"}, ReturnValues="ALL_OLD"
    ).get("Attributes")
    if deleted_pair:
        table.delete_item(Key={"pk": pair_deleting_item["pk"], "sk": pair_deleting_item["sk"]})
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


def get_unfinished_pair_creating(user_chat_id):
    return table.get_item(Key=({"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_CREATING"})).get("Item")


def get_unfinished_pair_deleting(user_chat_id):
    return table.get_item(Key=({"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_DELETING"})).get("Item")


def delete_unfinished_operations(user_chat_id):
    deleted_creating = table.delete_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_CREATING"}, ReturnValues="ALL_OLD"
    )
    deleted_deleting = table.delete_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": "TRANSLATION_PAIR_DELETING"}, ReturnValues="ALL_OLD"
    )
    return deleted_creating.get("Attributes"), deleted_deleting.get("Attributes")


@handle_unexpected_error
def handler(event, _):
    update = Update.de_json(json.loads(event.get("body")), bot)

    user_chat_id = update.message.chat.id
    text = update.message.text

    if text.startswith("/add_pair"):
        if get_unfinished_pair_creating(user_chat_id) or get_unfinished_pair_deleting(user_chat_id):
            bot.sendMessage(chat_id=user_chat_id, text="Please, finish current operation or cancel it (/cancel)")
            return {"statusCode": HTTPStatus.OK}

        create_translation_pair(user_chat_id)
        bot.sendMessage(chat_id=user_chat_id, text=ASK_FOR_ENGLISH)
    elif text.startswith("/delete_pair"):
        if get_unfinished_pair_creating(user_chat_id) or get_unfinished_pair_deleting(user_chat_id):
            bot.sendMessage(chat_id=user_chat_id, text="Please, finish current operation or cancel it (/cancel)")
            return {"statusCode": HTTPStatus.OK}

        create_translation_pair_deleting(user_chat_id)
        bot.sendMessage(chat_id=user_chat_id, text=f"{ASK_FOR_ENGLISH} from the pair you want to delete")
    elif text.startswith("/list_pairs"):
        bot.sendMessage(chat_id=user_chat_id, text=list_translation_pairs_text(user_chat_id))
    elif text.startswith("/cancel"):
        if any(delete_unfinished_operations(user_chat_id)):
            bot.sendMessage(chat_id=user_chat_id, text="Operation is canceled")
        else:
            bot.sendMessage(chat_id=user_chat_id, text="There is no active operations")
    elif text.startswith("/set_polling_rate"):
        command_parts = text.split(" ")
        time_amount = command_parts[-1]
        if len(command_parts) < 2:
            bot.sendMessage(
                chat_id=user_chat_id,
                text=(
                    "You need to pass the rate right after the command and space. "
                    "For example '/set_polling_rate_in_minutes 15'"
                ),
            )
            return {"statusCode": HTTPStatus.OK}
        elif not time_amount or not time_amount.isdigit():
            bot.sendMessage(chat_id=user_chat_id, text="Specified rate is incorrect. Please, try again.")
            return {"statusCode": HTTPStatus.OK}

        time_units = text.split(" ")[0].split("/set_polling_rate_in_")[-1]
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
                {"Arn": POLLING_LAMBDA_ARN, "Id": "POLLING_LAMBDA", "Input": json.dumps({"user_chat_id": user_chat_id})}
            ],
        )
        lambda_client.add_permission(
            FunctionName=POLLING_LAMBDA_ARN,
            StatementId=f"PERIODIC_{user_chat_id}_POLLING_PERMISSION",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
        bot.sendMessage(chat_id=user_chat_id, text=f"Okay, I will poll you every {time_amount} {time_units}")
    else:
        # Text from customer for some operation
        if unfinished_pair_creating := get_unfinished_pair_creating(user_chat_id):
            if unfinished_pair_creating.get("english_text"):
                add_native_text_to_pair(unfinished_pair_creating, text)
                bot.sendMessage(chat_id=user_chat_id, text="New pair is added")
                return {"statusCode": HTTPStatus.OK}
            else:
                add_english_text_to_pair(user_chat_id, text)
                bot.sendMessage(chat_id=user_chat_id, text=ASK_FOR_TRANSLATION)
        if unfinished_pair_deleting := get_unfinished_pair_deleting(user_chat_id):
            if delete_translation_pair(unfinished_pair_deleting, text):
                bot.sendMessage(chat_id=user_chat_id, text="Translation pair is deleted")
            else:
                bot.sendMessage(
                    chat_id=user_chat_id,
                    text="There is no pair with such english phrase. Please, try again or cancel operation (/cancel)",
                )

    return {"statusCode": HTTPStatus.OK}
