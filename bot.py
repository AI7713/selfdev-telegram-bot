import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен из переменных окружения Render
TOKEN = os.getenv('TELEGRAM_TOKEN')

# Состояния для ConversationHandler
MAIN_MENU, PRODUCT_MENU = range(2)

# Демо-ответы для продуктов
DEMO_RESPONSES = {
    'гримуар': '🔮 Это демо-версия Гримуара. В платной версии вы получите персонализированные советы по самопознанию через метафоры и архетипы.',
    'переговорщик': '💼 Это демо-версия Переговорщика. В платной версии вы получите персональные стратегии для сложных переговоров на основе вашей ситуации.'
}

async def start(update: Update, context: CallbackContext) -> int:
    """Начало работы с ботом - показывает главное меню"""
    user = update.message.from_user
    logger.info(f"Пользователь {user.first_name} начал работу с ботом")
    
    # Создаем клавиатуру главного меню
    keyboard = [
        [KeyboardButton("🔮 Гримуар")],
        [KeyboardButton("💼 Переговорщик")],
        [KeyboardButton("ℹ️ О боте")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🎭 Добро пожаловать в бот саморазвития!\n\n"
        "Выберите продукт для знакомства:",
        reply_markup=reply_markup
    )
    
    return MAIN_MENU

async def handle_main_menu(update: Update, context: CallbackContext) -> int:
    """Обработка выбора в главном меню"""
    text = update.message.text
    user = update.message.from_user
    
    if text == "🔮 Гримуар":
        logger.info(f"Пользователь {user.first_name} выбрал Гримуар")
        return await show_product_menu(update, context, 'гримуар')
    
    elif text == "💼 Переговорщик":
        logger.info(f"Пользователь {user.first_name} выбрал Переговорщик")
        return await show_product_menu(update, context, 'переговорщик')
    
    elif text == "ℹ️ О боте":
        await update.message.reply_text(
            "🤖 Этот бот помогает в самопознании и развитии навыков.\n\n"
            "🔮 Гримуар - инструмент для самопознания через метафоры\n"
            "💼 Переговорщик - помощник в сложных диалогах\n\n"
            "Каждый продукт имеет демо-версию и платный доступ к AI-помощнику."
        )
        return MAIN_MENU
    
    else:
        await update.message.reply_text("Пожалуйста, выберите вариант из меню:")
        return MAIN_MENU

async def show_product_menu(update: Update, context: CallbackContext, product: str) -> int:
    """Показывает меню конкретного продукта"""
    context.user_data['current_product'] = product
    
    product_names = {
        'гримуар': '🔮 Гримуар',
        'переговорщик': '💼 Переговорщик'
    }
    
    product_descriptions = {
        'гримуар': 'Инструмент для самопознания через метафоры и архетипы',
        'переговорщик': 'Помощник в подготовке и ведении сложных переговоров'
    }
    
    keyboard = [
        [KeyboardButton("🆓 Попробовать")],
        [KeyboardButton("💳 Платный доступ")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"{product_names[product]}\n\n"
        f"{product_descriptions[product]}\n\n"
        "Выберите вариант:",
        reply_markup=reply_markup
    )
    
    return PRODUCT_MENU

async def handle_product_menu(update: Update, context: CallbackContext) -> int:
    """Обработка выбора в меню продукта"""
    text = update.message.text
    product = context.user_data.get('current_product', 'unknown')
    user = update.message.from_user
    
    if text == "🆓 Попробовать":
        logger.info(f"Пользователь {user.first_name} пробует демо {product}")
        demo_text = DEMO_RESPONSES.get(product, 'Демо-версия временно недоступна.')
        await update.message.reply_text(demo_text)
        return PRODUCT_MENU
    
    elif text == "💳 Платный доступ":
        logger.info(f"Пользователь {user.first_name} запросил платный доступ к {product}")
        await update.message.reply_text(
            "🚀 Платный доступ откроет:\n\n"
            "• Живое общение с AI-помощником\n"
            "• Персонализированные ответы\n" 
            "• Полный функционал продукта\n"
            "• Доступ на 5 дней\n\n"
            "Скоро здесь будет возможность приобрести доступ!"
        )
        return PRODUCT_MENU
    
    elif text == "🔙 Назад":
        return await start(update, context)
    
    else:
        await update.message.reply_text("Пожалуйста, выберите вариант из меню:")
        return PRODUCT_MENU

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        'До свидания! Чтобы начать заново, отправьте /start',
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return ConversationHandler.END

def main():
    """Основная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Настраиваем обработчики
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)
            ],
            PRODUCT_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_menu)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(conv_handler)
    
    # Запускаем бота
    logger.info("Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == '__main__':
    main()
