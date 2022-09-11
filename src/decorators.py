from http import HTTPStatus

from aws_lambda_powertools import Logger

logger = Logger()


def handle_unexpected_error(f):
    def wrapper(event, context):
        try:
            return f(event, context)
        except Exception:
            logger.exception("Unexpected error.")
            return {"statusCode": HTTPStatus.OK}

    return wrapper
