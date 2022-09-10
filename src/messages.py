import json
import os
from http import HTTPStatus

from aws_lambda_powertools import Logger
from boto3 import resource
from boto3.dynamodb.conditions import Key
from telegram import Update, Bot


logger = Logger()
table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))

ASK_FOR_ENGLISH = "Send me the text of english phrase/word"
ASK_FOR_TRANSLATION = "Send me the translation"


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


def list_translation_pairs_text(user_chat_id):
    query_result = table.query(
        KeyConditionExpression=(Key("pk").eq(f"USER#{user_chat_id}") & Key("sk").begins_with("TRANSLATION_PAIR#"))
    )
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


def handle_unexpected_error(f):
    def wrapper(event, context):
        try:
            return f(event, context)
        except Exception:
            logger.exception("Unexpected error.")
            return {"statusCode": HTTPStatus.OK}

    return wrapper


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
