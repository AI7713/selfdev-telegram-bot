import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

TOKEN = os.getenv('TELEGRAM_TOKEN')

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('🎉 Бот работает! Добро пожаловать!')

async def echo(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(f'Вы написали: {update.message.text}')

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.run_polling()

if __name__ == '__main__':
    main()
