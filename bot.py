import os
import logging
import random
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен из переменных окружения Render
TOKEN = os.getenv('TELEGRAM_TOKEN')

# Состояния для ConversationHandler
MAIN_MENU, PRODUCT_MENU, DEMO_SCENARIOS = range(3)

# Улучшенные демо-сценарии для продуктов
DEMO_SCENARIOS = {
    'гримуар': {
        'архетипы': {
            'question': '🔮 Какие архетипы проявляются в вашей жизни сейчас?',
            'demo_answer': 'В платной версии вы получите:\n• Анализ доминирующих архетипов\n• Рекомендации по работе с ними\n• Персональные метафоры для роста\n\n💫 Пример: Если проявляется "Воин" - фокус на действиях, если "Мудрец" - на анализе.',
            'teaser': 'Узнайте какие 5 архетипов управляют вашими решениями!'
        },
        'метафоры': {
            'question': '🌌 Какую метафору выбрать для вашего жизненного этапа?',
            'demo_answer': 'Полная версия предложит:\n• Метафору текущего этапа жизни\n• Символы для трансформации\n• Практики для интеграции\n\n🎭 Пример: "Ваша жизнь как сад" или "Путешествие героя".',
            'teaser': 'Откройте метафору, которая изменит ваше восприятие!'
        },
        'самопознание': {
            'question': '🧠 Как углубить самопознание через символы?',
            'demo_answer': 'В платном доступе:\n• Диагностика через символы\n• Персональные практики\n• Ежедневные инсайты\n\n📖 Пример: Работа с образами воды, огня, земли и воздуха.',
            'teaser': 'Превратите самопознание в увлекательное путешествие!'
        }
    },
    'переговорщик': {
        'конфликт': {
            'question': '⚡ Как вести себя в конфликтной ситуации?',
            'demo_answer': 'Платная версия даст:\n• Стратегию деэскалации\n• Техники активного слушания\n• Сценарии для разных типов конфликтов\n\n🛡️ Пример: Метод "Я-высказываний" и техника "Зеркало".',
            'teaser': 'Научитесь превращать конфликты в возможности!'
        },
        'подготовка': {
            'question': '📋 Как подготовиться к сложным переговорам?',
            'demo_answer': 'Полный доступ включает:\n• Чек-лист подготовки\n• Анализ позиций сторон\n• Прогнозирование возражений\n\n🎯 Пример: Метод BATNA - лучшая альтернатива переговорному соглашению.',
            'teaser': 'Подготовьтесь так, чтобы переговоры шли по вашему сценарию!'
        },
        'возражения': {
            'question': '🛡️ Как работать с возражениями?',
            'demo_answer': 'В платной версии:\n• Типология возражений\n• Алгоритмы ответов\n• Тренировка реакций\n\n💡 Пример: Техника "Согласие и развитие" вместо спора.',
            'teaser': 'Научитесь видеть в возражениях скрытые потребности!'
        }
    }
}

# Случайные тизеры для кнопки "Попробовать"
DEMO_TEASERS = {
    'гримуар': [
        "🔮 Узнайте какие архетипы управляют вашей жизнью",
        "🌌 Откройте метафору для вашего жизненного этапа", 
        "🧠 Начните глубинное самопознание через символы",
        "📖 Превратите самопознание в увлекательное путешествие"
    ],
    'переговорщик': [
        "⚡ Научитесь управлять конфликтными ситуациями",
        "📋 Подготовьтесь к переговорам как профессионал",
        "🛡️ Освойте работу с возражениями",
        "💡 Превращайте возражения в возможности"
    ]
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
        "🎭 Добро welcome в бот саморазвития!\n\n"
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
            "🔮 Гримуар - инструмент для самопознания через метафоры и архетипы\n"
            "💼 Переговорщик - помощник в сложных диалогах и переговорах\n\n"
            "Каждый продукт имеет интерактивное демо и платный доступ к AI-помощнику."
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
        return await show_demo_scenarios(update, context, product)
    
    elif text == "💳 Платный доступ":
        logger.info(f"Пользователь {user.first_name} запросил платный доступ к {product}")
        await update.message.reply_text(
            "🚀 Платный доступ откроет:\n\n"
            "• Живое общение с AI-помощником\n"
            "• Персонализированные ответы на ваши вопросы\n" 
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

async def show_demo_scenarios(update: Update, context: CallbackContext, product: str) -> int:
    """Показывает сценарии для демо-версии"""
    # Выбираем случайный тизер
    teaser = random.choice(DEMO_TEASERS[product])
    
    # Создаем клавиатуру сценариев
    scenarios = DEMO_SCENARIOS[product]
    keyboard = []
    for scenario_key in scenarios.keys():
        keyboard.append([KeyboardButton(scenarios[scenario_key]['question'])])
    keyboard.append([KeyboardButton("🔙 Назад")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"{teaser}\n\n"
        "Выберите интересующий вас аспект:",
        reply_markup=reply_markup
    )
    
    return DEMO_SCENARIOS

async def handle_demo_scenarios(update: Update, context: CallbackContext) -> int:
    """Обработка выбора демо-сценария"""
    text = update.message.text
    product = context.user_data.get('current_product', 'unknown')
    user = update.message.from_user
    
    if text == "🔙 Назад":
        return await show_product_menu(update, context, product)
    
    # Ищем выбранный сценарий
    scenarios = DEMO_SCENARIOS[product]
    for scenario_key, scenario_data in scenarios.items():
        if scenario_data['question'] == text:
            logger.info(f"Пользователь {user.first_name} выбрал сценарий {scenario_key} для {product}")
            
            await update.message.reply_text(
                f"{scenario_data['demo_answer']}\n\n"
                f"💎 {scenario_data['teaser']}"
            )
            
            # Предлагаем выбрать еще сценарий или вернуться
            keyboard = [
                [KeyboardButton("🎯 Выбрать другой сценарий")],
                [KeyboardButton("🔙 В меню продукта")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Что хотите сделать дальше?",
                reply_markup=reply_markup
            )
            return DEMO_SCENARIOS
    
    # Если сценарий не найден
    await update.message.reply_text("Пожалуйста, выберите вариант из меню:")
    return DEMO_SCENARIOS

async def handle_demo_actions(update: Update, context: CallbackContext) -> int:
    """Обработка действий после демо"""
    text = update.message.text
    product = context.user_data.get('current_product', 'unknown')
    
    if text == "🎯 Выбрать другой сценарий":
        return await show_demo_scenarios(update, context, product)
    elif text == "🔙 В меню продукта":
        return await show_product_menu(update, context, product)
    else:
        await update.message.reply_text("Пожалуйста, выберите вариант из меню:")
        return DEMO_SCENARIOS

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
            DEMO_SCENARIOS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo_scenarios),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo_actions)
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
