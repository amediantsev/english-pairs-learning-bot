import json
import os
from http import HTTPStatus
from contextlib import suppress

import telegram
from aws_lambda_powertools import Logger
from boto3 import client
from telegram import Update
from telegram.error import Unauthorized

from aws import dynamodb as dynamodb_operations
from aws.events_bridge import put_event, put_targets, get_rule
from aws.translate import translate_text
from decorators import handle_errors
from exceptions import ProcessMessageError
from helpers import get_polling_rule_name
from tg import Chat, bot, send_message, ADMIN_IDS
from users import remove_user

ASK_FOR_ENGLISH = "Send me the text of english phrase/word"
ASK_FOR_RATE = "Send me the rate of how often you want to get polls"
HELLO_MESSAGE = (
    "Hello buddy! This bot will help you to learn new english words and phrases.\n\n"
    r"You should just add them here with /add\_pair command "
    "and bot will periodically send you polls with translation options.\n"
    "Default period is 1 hour, but you can change it to any you want "
    r"with /set\_polling\_rate\_in\_minutes or /set\_polling\_rate\_in\_hours commands."
    "\n\nWhen you understand that you know some of your word/phrase really well, "
    r"you can exclude it from polls with /delete\_pair command."
    "\n\n"
    r"You can also see all your words/phrases with /list\_pairs command."
    "\n\nPlease, enjoy and become smarter every day!"
    "\nIf you found something is broken or want to suggest some improvement, "
    "please contact me, the author, @ZenCrazyCat"
)
HELLO_MESSAGE_UK = (
    "Привіт, друже! Цей бот допоможе тобі вивчити нові англійські слова та фрази.\n\n"
    r"Тобі треба просто додати їх сюди за допомогою команди /add\_pair "
    "і бот періодично надсилатиме тобі опитування з варіантами перекладу.\n"
    "Періодичність за замовчуванням становить 1 годину, але ти можеш змінити її на будь-яку іншу"
    r"за допомогою команд /set\_polling\_rate\_in\_minutes або /set\_polling\_rate\_in\_hours."
    "\n\nКоли ти розумієш, що вже добре вивчив якесь своє слово/фразу, "
    r"ти можеш виключити її з опитувань за допомогою команди /delete\_pair."
    "\n\n"
    r"Ти також можеш переглянути всі свої слова/фрази за допомогою команди /list\_pairs."
    "\n\nБудь ласка, насолоджуйся і ставай розумнішим з кожним днем!"
    "\nЯкщо ти виявив, що щось зламано або просто хочеш запропонувати якісь покращення, "
    "будь ласка, зв'яжись зі мною, автором, @ZenCrazyCat"
)
EN_UK_SPLITTER = f"\n\n{'~' * 25}\n\n"
TIP_LENGTH_MULTIPLIER = 1.7
POLLING_LAMBDA_ARN = os.getenv("POLLING_LAMBDA_ARN")

logger = Logger()
lambda_client = client("lambda")


def list_translation_pairs_text(user_chat_id):
    translation_pairs = dynamodb_operations.list_translation_pairs(user_chat_id)
    result_text = f"Count: {len(translation_pairs)}\n\n"
    for pair in translation_pairs:
        correct_answers = pair.get("correct_answers", 0)
        wrong_answers = pair.get("wrong_answers", 0)
        all_answers = correct_answers + wrong_answers
        correct_percentage = 0 if all_answers == 0 else correct_answers * 100 / all_answers
        result_text += (
            f"**{pair['english_text']} - {pair['native_text']}**\n"
            f"_(polled {pair.get('polls_count', 0)} times - "
            f"{correct_answers}✅ {wrong_answers}⛔ - {int(round(correct_percentage, 0))}%)_\n\n"
        )

    return result_text


def setup_polling(user_chat_id, time_amount, time_units):
    rule_name = get_polling_rule_name(user_chat_id)
    rule_arn = put_event(rule_name, f"rate({time_amount} {time_units})")
    put_targets(
        rule_name,
        [
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


@handle_errors
def handler(event, _):
    logger.info(event)
    update = Update.de_json(json.loads(event.get("body")), bot)
    if poll := update.poll:
        if poll.type == telegram.Poll.QUIZ:
            answered_correctly = bool(poll.options[poll.correct_option_id]["voter_count"])
            pair_stats_field_to_increment = "correct_answers" if answered_correctly else "wrong_answers"
            saved_poll_info = dynamodb_operations.get_poll(poll.id)
            dynamodb_operations.increment_translation_pair_fields(
                saved_poll_info["user_chat_id"],
                saved_poll_info["english_text"],
                **{pair_stats_field_to_increment: 1},
            )
            dynamodb_operations.delete_poll(poll.id)
            return {"statusCode": HTTPStatus.OK}

        if not poll.options[0]["voter_count"]:
            return {"statusCode": HTTPStatus.OK}
        suggestion_info = dynamodb_operations.get_suggestion(poll.id)
        dynamodb_operations.create_translation_pair(
            user_chat_id=suggestion_info["user_chat_id"],
            english_text=suggestion_info["english_text"],
            native_text=suggestion_info["native_text"],
        )
        send_message(user_chat_id=suggestion_info["user_chat_id"], text="New translation pair is added")
        return {"statusCode": HTTPStatus.OK}

    if not update.message:
        return {"statusCode": HTTPStatus.OK}
    chat = Chat(tg_update_obj=update)
    event["user_chat_id"] = user_chat_id = chat.id
    text = chat.text.strip()
    if text.startswith("/start"):
        chat.send_message(text=f"{HELLO_MESSAGE}{EN_UK_SPLITTER}{HELLO_MESSAGE_UK}")
        dynamodb_operations.create_user(user_chat_id, chat.username)
        if not get_rule(get_polling_rule_name(user_chat_id)):
            setup_polling(user_chat_id, time_amount=1, time_units="hour")
    elif text.startswith("/add_pair"):
        dynamodb_operations.create_current_action(user_chat_id, "TRANSLATION_PAIR_CREATING")
        chat.send_message(text=ASK_FOR_ENGLISH)
    elif text.startswith("/delete_pair"):
        dynamodb_operations.create_current_action(user_chat_id, "TRANSLATION_PAIR_DELETING")
        chat.send_message(text=f"{ASK_FOR_ENGLISH} from the pair you want to delete")
    elif text.startswith("/list_pairs"):
        chat.send_message(text=list_translation_pairs_text(user_chat_id))
    elif text.startswith("/cancel"):
        if dynamodb_operations.delete_current_action(user_chat_id):
            chat.send_message(text="Operation is canceled")
        else:
            raise ProcessMessageError(message="There is no active operations")
    elif text.startswith("/set_polling_rate"):
        time_units = text.split(" ")[0].split("/set_polling_rate_in_")[-1]
        dynamodb_operations.create_current_action(user_chat_id, "POLLING_RATE_UPDATE", time_units=time_units)
        chat.send_message(text=f"{ASK_FOR_RATE} in {time_units}")
    elif text.startswith("/notify_users"):
        command_and_message = text.split("/notify_users ")
        message = command_and_message[-1]
        if str(user_chat_id) not in ADMIN_IDS:
            raise ProcessMessageError(message=f"Sorry, you are not admin")
        if len(command_and_message) == 1 or not message:
            raise ProcessMessageError(message="You didn't pass any message to users. Do it after command and space")

        for user in dynamodb_operations.list_users():
            try:
                send_message(str(user["user_chat_id"]), text=message, disable_markdown=True)
            except Unauthorized:
                logger.error(f"user {user_chat_id} has blocked bot")
                remove_user(str(user["user_chat_id"]), POLLING_LAMBDA_ARN)
    else:
        # Data from customer for some current operation (action)
        if not (current_action := dynamodb_operations.get_current_action(user_chat_id)):
            return {"statusCode": HTTPStatus.OK}

        text = text.replace("*", "").replace("_", "").replace("`", "")
        current_action_type = current_action["action_type"]
        if current_action_type == "TRANSLATION_PAIR_CREATING":
            if english_text := current_action.get("english_text"):
                dynamodb_operations.create_translation_pair(
                    user_chat_id, english_text, native_text=current_action.get("native_text") if text == "+" else text
                )
                chat.send_message(text="New translation pair is added")
            else:
                suggested_translation = translate_text(text)
                dynamodb_operations.update_current_action(
                    user_chat_id, english_text=text, native_text=suggested_translation
                )
                chat.send_message(
                    text=(
                        "Now, send me the translation\n\n"
                        f"_Or use the suggested one - _**'{suggested_translation}'**_ (just send '+' to use it)_"
                        f"{EN_UK_SPLITTER}"
                        "Тепер, надішли мені переклад\n\n"
                        f"_Або використай запропонований - _**'{suggested_translation}'**_ "
                        "(просто надішли '+', щоб використати його)_"
                    )
                )
        elif current_action_type == "TRANSLATION_PAIR_DELETING":
            if dynamodb_operations.delete_translation_pair(user_chat_id, text):
                chat.send_message(text="Translation pair is deleted")
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
                # 'hours' -> 'hour', 'minutes' -> 'minute'
                time_units = time_units[:-1]
            setup_polling(user_chat_id, time_amount, time_units)
            dynamodb_operations.delete_current_action(user_chat_id)
            chat.send_message(text=f"Okay, I will poll you every {time_amount} {time_units}")
        elif current_action_type == "OPEN_QUESTION":
            full_answer = current_action["answer"].lower()
            possible_answers = {
                full_answer,
                *[answer.strip().replace("(", "").replace(")", "") for answer in full_answer.split(",")],
            }
            if text.lower() in possible_answers:
                pair_stats_field_to_increment = "correct_answers"
                message_to_send = "Correct ✅ Good job!"
                dynamodb_operations.delete_current_action(user_chat_id)
            else:
                pair_stats_field_to_increment = "wrong_answers"
                message_to_send = "Sorry, it's wrong ⛔ Please, try again. "
                mistakes_count = int(round(float(current_action.get("translation_tip_length", 1)) * 1.7, 0))
                message_to_send += (
                    f"\n\nA little tip: _'{full_answer[:mistakes_count]}{'*' * (len(full_answer) - mistakes_count)}'_"
                )
                dynamodb_operations.update_current_action(user_chat_id, translation_tip_length=mistakes_count)

            dynamodb_operations.increment_translation_pair_fields(
                user_chat_id,
                current_action["english_text"],
                **{pair_stats_field_to_increment: 1},
            )
            chat.send_message(message_to_send)

    return {"statusCode": HTTPStatus.OK}
