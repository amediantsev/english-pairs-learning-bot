import os

from telegram import Bot, ParseMode


ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")

bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


def send_message(user_chat_id, text, disable_markdown=False):
    send_message_kwargs = {"chat_id": user_chat_id, "text": text}
    if not disable_markdown:
        send_message_kwargs["parse_mode"] = ParseMode.MARKDOWN
    bot.sendMessage(**send_message_kwargs)


class Chat:
    def __init__(self, tg_update_obj):
        self.id = tg_update_obj.message.chat.id
        self.text = tg_update_obj.message.text
        self.username = tg_update_obj.message.chat.username

    def send_message(self, text):
        send_message(user_chat_id=self.id, text=text)
