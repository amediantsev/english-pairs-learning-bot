from contextlib import suppress

from boto3 import client

events_client = client("events")


def put_event(rule_name, schedule_expression):
    return events_client.put_rule(Name=rule_name, ScheduleExpression=schedule_expression, State="ENABLED")["RuleArn"]


def put_targets(rule_name, targets):
    events_client.put_targets(Rule=rule_name, Targets=targets)


def get_rule(rule_name):
    try:
        return events_client.describe_rule(Name=rule_name)
    except events_client.exceptions.ResourceNotFoundException:
        return


def delete_rule(rule_name):
    with suppress(events_client.exceptions.ResourceNotFoundException):
        if targets := events_client.list_targets_by_rule().get("Targets", []):
            events_client.remove_targets(Rule=rule_name, Ids=[target["Id"] for target in targets])
    with suppress(events_client.exceptions.ResourceNotFoundException):
        events_client.delete_rule(Rule=rule_name)
