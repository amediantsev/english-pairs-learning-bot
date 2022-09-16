import os
from contextlib import suppress

from boto3 import client

from aws.dynamodb import delete_all_user_items
from aws.events_bridge import delete_rule
from helpers import get_polling_rule_name


lambda_client = client("lambda")


def remove_user(user_chat_id, polling_lambda_arn):
    # Delete all resources related to the user
    delete_all_user_items(user_chat_id)
    with suppress(lambda_client.exceptions.ResourceNotFoundException):
        lambda_client.remove_permission(
            FunctionName=polling_lambda_arn,
            StatementId=f"PERIODIC_{user_chat_id}_POLLING_PERMISSION",
        )
    delete_rule(get_polling_rule_name(user_chat_id))
