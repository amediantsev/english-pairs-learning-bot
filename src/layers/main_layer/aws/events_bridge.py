from boto3 import client

events_client = client("events")


def put_event(rule_name, schedule_expression):
    return events_client.put_rule(Name=rule_name, ScheduleExpression=schedule_expression, State="ENABLED")["RuleArn"]


def put_targets(rule_name, targets):
    events_client.put_targets(Rule=rule_name, Targets=targets)
