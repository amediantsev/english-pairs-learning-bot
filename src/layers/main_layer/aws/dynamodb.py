import os

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
            "user_chat_id": user_chat_id,
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
            "user_chat_id": user_chat_id,
            "english_text": english_text,
            "native_text": native_text,
            "polls_count": 0,
        }
    )
    delete_current_action(user_chat_id)


def increment_translation_pair_fields(user_chat_id, english_text, **kwargs):
    table.update_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": f"TRANSLATION_PAIR#{english_text}"},
        AttributeUpdates={k: {"Value": v, "Action": "ADD"} for k, v in kwargs.items()},
    )


def create_poll(user_chat_id, poll_id, english_text):
    table.put_item(
        Item={
            "pk": f"POLL#{poll_id}",
            "sk": f"POLL#{poll_id}",
            "user_chat_id": user_chat_id,
            "gsi1pk": f"USER#{user_chat_id}",
            "gsi1sk": f"POLL#{poll_id}",
            "answered": False,
            "english_text": english_text,
        }
    )


def get_poll(poll_id):
    return table.get_item(Key={"pk": f"POLL#{poll_id}", "sk": f"POLL#{poll_id}"}).get("Item")


def update_poll(poll_id, **kwargs):
    table.update_item(
        Key={"pk": f"POLL#{poll_id}", "sk": f"POLL#{poll_id}"},
        AttributeUpdates={k: {"Value": v, "Action": "PUT"} for k, v in kwargs.items()},
    )


def delete_poll(poll_id):
    table.delete_item(Key={"pk": f"POLL#{poll_id}", "sk": f"POLL#{poll_id}"})


def delete_translation_pair(user_chat_id, english_text):
    deleted_pair = table.delete_item(
        Key={"pk": f"USER#{user_chat_id}", "sk": f"TRANSLATION_PAIR#{english_text}"}, ReturnValues="ALL_OLD"
    ).get("Attributes")
    if deleted_pair:
        delete_current_action(user_chat_id)
    return deleted_pair


def list_translation_pairs(user_chat_id):
    return sorted(
        table.query(
            KeyConditionExpression=(Key("pk").eq(f"USER#{user_chat_id}") & Key("sk").begins_with("TRANSLATION_PAIR#"))
        )["Items"],
        key=lambda x: x["english_text"],
    )


def delete_all_user_items(user_chat_id):
    items = [
        *table.query(KeyConditionExpression=(Key("pk").eq(f"USER#{user_chat_id}")))["Items"],
        *table.query(IndexName="gsi1", KeyConditionExpression=(Key("gsi1pk").eq(f"USER#{user_chat_id}")))["Items"],
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
