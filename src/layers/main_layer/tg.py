import os

from telegram import Bot, ParseMode, Update


bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))


class Chat:
    def __init__(self, tg_request_body):
        update = Update.de_json(tg_request_body, bot)
        self.id = update.message.chat.id
        self.text = update.message.text

    def send_message(self, text):
        bot.sendMessage(chat_id=self.id, text=text, parse_mode=ParseMode.MARKDOWN)
