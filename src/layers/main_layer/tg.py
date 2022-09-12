import os

from telegram import Bot, ParseMode


bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


class Chat:
    def __init__(self, tg_update_obj):
        self.id = tg_update_obj.message.chat.id
        self.text = tg_update_obj.message.text

    def send_message(self, text):
        bot.sendMessage(chat_id=self.id, text=text, parse_mode=ParseMode.MARKDOWN)
