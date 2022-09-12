import os
from datetime import datetime

from boto3 import resource
from boto3.dynamodb.conditions import Key

from exceptions import ProcessMessageError


table = resource("dynamodb").Table(os.getenv("TABLE_NAME"))


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
    return table.delete_item(Key={"pk": f"USER#{user_chat_id}", "sk": "CURRENT_ACTION"}, ReturnValues="ALL_OLD").get(
        "Attributes"
    )


def create_translation_pair(user_chat_id, english_text, native_text):
    table.put_item(
        Item={
            "pk": f"USER#{user_chat_id}",
            "sk": f"TRANSLATION_PAIR#{english_text}",
            "user_id": user_chat_id,
            "english_text": english_text,
            "native_text": native_text,
            "polls_count": 0,
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
    )["Items"]
