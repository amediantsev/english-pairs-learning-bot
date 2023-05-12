import datetime
import os
import time

from boto3 import resource
from boto3.dynamodb.conditions import Key, Attr

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
            "gsi1pk": "TRANSLATION_PAIR",
            "created_at": datetime.datetime.now().isoformat(),
            "active": True,
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


def create_suggestion(user_chat_id, poll_id, new_words: list[tuple[str, str]]):
    table.put_item(
        Item={
            "pk": f"SUGGESTION#{poll_id}",
            "sk": f"SUGGESTION#{poll_id}",
            "user_chat_id": user_chat_id,
            "gsi1pk": f"USER#{user_chat_id}",
            "gsi1sk": f"SUGGESTION#{poll_id}",
            "new_words": new_words,
        }
    )


def get_poll(poll_id):
    return table.get_item(Key={"pk": f"POLL#{poll_id}", "sk": f"POLL#{poll_id}"}).get("Item", {})


def get_suggestion(poll_id):
    return table.get_item(Key={"pk": f"SUGGESTION#{poll_id}", "sk": f"SUGGESTION#{poll_id}"}).get("Item", {})


def update_poll(poll_id, **kwargs):
    table.update_item(
        Key={"pk": f"POLL#{poll_id}", "sk": f"POLL#{poll_id}"},
        AttributeUpdates={k: {"Value": v, "Action": "PUT"} for k, v in kwargs.items()},
    )


def delete_poll(poll_id):
    table.delete_item(Key={"pk": f"POLL#{poll_id}", "sk": f"POLL#{poll_id}"})


def mark_translation_pair_inactive(user_chat_id, english_text) -> bool:
    key = {"pk": f"USER#{user_chat_id}", "sk": f"TRANSLATION_PAIR#{english_text}"}
    if not table.get_item(Key=key).get("Item"):
        return False
    table.update_item(Key=key, AttributeUpdates={"active": {"Value": False, "Action": "PUT"}})
    delete_current_action(user_chat_id)
    return True


def list_translation_pairs(user_chat_id, limit=None):
    response = list(
        reversed(
            sorted(
                table.query(
                    KeyConditionExpression=(
                        Key("pk").eq(f"USER#{user_chat_id}") & Key("sk").begins_with("TRANSLATION_PAIR#")
                    ),
                    FilterExpression=Attr("active").eq(True),
                )["Items"],
                key=lambda x: x["created_at"],
            )
        )
    )
    return response[:limit] if limit else response


def delete_all_user_items(user_chat_id):
    deleted_translations_batch = []
    items = [
        *table.query(KeyConditionExpression=(Key("pk").eq(f"USER#{user_chat_id}")))["Items"],
        *table.query(IndexName="gsi1", KeyConditionExpression=(Key("gsi1pk").eq(f"USER#{user_chat_id}")))["Items"],
    ]
    with table.batch_writer() as batch:
        for item in items:
            if "sk".startswith("DELETED_TRANSLATIONS_BATCH#"):
                continue
            if "sk".startswith("TRANSLATION_PAIR#"):
                deleted_translations_batch.append(item)
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    if deleted_translations_batch:
        table.put_item(
            Item={
                "pk": f"USER#{user_chat_id}",
                "sk": f"DELETED_TRANSLATIONS_BATCH#{time.time()}",
                "user_chat_id": user_chat_id,
                "gsi1pk": "DELETED_TRANSLATIONS_BATCH",
                "deleted_translations_batch": items,
            }
        )


def list_users():
    return table.query(IndexName="gsi1", KeyConditionExpression=(Key("gsi1pk").eq("USER")))["Items"]


def create_user(user_chat_id, username):
    table.put_item(
        Item={
            "pk": f"USER#{user_chat_id}",
            "sk": f"USER#{user_chat_id}",
            "gsi1pk": "USER",
            "gsi1sk": f"USER#{user_chat_id}",
            "user_chat_id": user_chat_id,
            "username": username,
        }
    )


def get_user(user_chat_id):
    return table.get_item(Key={"pk": f"USER#{user_chat_id}", "sk": f"USER#{user_chat_id}"}).get("Item") or {}
