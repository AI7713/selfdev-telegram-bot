import os
import logging
import random
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_TOKEN')

# Улучшенные демо-сценарии
DEMO_SCENARIOS = {
    'гримуар': {
        'архетипы': '🔮 В платной версии: анализ ваших архетипов, рекомендации по работе с ними, персональные метафоры для роста.',
        'метафоры': '🌌 Полная версия: метафора вашего жизненного этапа, символы для трансформации, практики для интеграции.',
        'самопознание': '🧠 Платный доступ: диагностика через символы, персональные практики, ежедневные инсайты.'
    },
    'переговорщик': {
        'конфликт': '⚡ В платной версии: стратегия деэскалации, техники активного слушания, сценарии для конфликтов.',
        'подготовка': '📋 Полный доступ: чек-лист подготовки, анализ позиций сторон, прогнозирование возражений.',
        'возражения': '🛡️ Платная версия: типология возражений, алгоритмы ответов, тренировка реакций.'
    }
}

class BotState:
    def __init__(self):
        self.user_states = {}

bot_state = BotState()

async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    logger.info(f"Пользователь {user.first_name} начал работу")
    
    # Сброс состояния пользователя
    bot_state.user_states[user.id] = 'MAIN_MENU'
    
    keyboard = [
        [KeyboardButton("🔮 Гримуар")],
        [KeyboardButton("💼 Переговорщик")],
        [KeyboardButton("ℹ️ О боте")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🎭 Добро пожаловать в бот саморазвития!\n\nВыберите продукт:",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    current_state = bot_state.user_states.get(user.id, 'MAIN_MENU')
    
    logger.info(f"Пользователь {user.first_name}: {text} (состояние: {current_state})")
    
    if current_state == 'MAIN_MENU':
        await handle_main_menu(update, context)
    elif current_state == 'PRODUCT_MENU':
        await handle_product_menu(update, context)
    elif current_state == 'DEMO_MENU':
        await handle_demo_menu(update, context)

async def handle_main_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    
    if text == "🔮 Гримуар":
        bot_state.user_states[user.id] = 'PRODUCT_MENU'
        context.user_data['current_product'] = 'гримуар'
        await show_product_menu(update, context, 'гримуар')
        
    elif text == "💼 Переговорщик":
        bot_state.user_states[user.id] = 'PRODUCT_MENU'
        context.user_data['current_product'] = 'переговорщик'
        await show_product_menu(update, context, 'переговорщик')
        
    elif text == "ℹ️ О боте":
        await update.message.reply_text(
            "🤖 Бот для самопознания и развития навыков.\n\n"
            "🔮 Гримуар - метафоры и архетипы\n"
            "💼 Переговорщик - сложные диалоги\n\n"
            "Демо-версия + платный доступ к AI."
        )
    else:
        await update.message.reply_text("Выберите вариант из меню:")

async def show_product_menu(update: Update, context: CallbackContext, product: str) -> None:
    product_names = {
        'гримуар': '🔮 Гримуар',
        'переговорщик': '💼 Переговорщик'
    }
    
    keyboard = [
        [KeyboardButton("🆓 Попробовать")],
        [KeyboardButton("💳 Платный доступ")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"{product_names[product]}\n\nВыберите вариант:",
        reply_markup=reply_markup
    )

async def handle_product_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    product = context.user_data.get('current_product', 'unknown')
    
    if text == "🆓 Попробовать":
        bot_state.user_states[user.id] = 'DEMO_MENU'
        await show_demo_scenarios(update, context, product)
        
    elif text == "💳 Платный доступ":
        await update.message.reply_text(
            "🚀 Платный доступ откроет:\n\n"
            "• Живое общение с AI\n"
            "• Персонализированные ответы\n" 
            "• Полный функционал\n"
            "• Доступ на 5 дней\n\n"
            "Скоро здесь можно будет приобрести доступ!"
        )
        
    elif text == "🔙 Назад":
        bot_state.user_states[user.id] = 'MAIN_MENU'
        await start(update, context)
    else:
        await update.message.reply_text("Выберите вариант из меню:")

async def show_demo_scenarios(update: Update, context: CallbackContext, product: str) -> None:
    scenarios = DEMO_SCENARIOS[product]
    
    keyboard = []
    if product == 'гримуар':
        keyboard = [
            [KeyboardButton("🔮 Архетипы")],
            [KeyboardButton("🌌 Метафоры")],
            [KeyboardButton("🧠 Самопознание")],
            [KeyboardButton("🔙 Назад")]
        ]
    else:
        keyboard = [
            [KeyboardButton("⚡ Конфликт")],
            [KeyboardButton("📋 Подготовка")],
            [KeyboardButton("🛡️ Возражения")],
            [KeyboardButton("🔙 Назад")]
        ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Выберите интересующий аспект:",
        reply_markup=reply_markup
    )

async def handle_demo_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    product = context.user_data.get('current_product', 'unknown')
    
    if text == "🔙 Назад":
        bot_state.user_states[user.id] = 'PRODUCT_MENU'
        await show_product_menu(update, context, product)
        return
    
    # Обработка выбора сценария
    scenario_map = {
        '🔮 Архетипы': 'архетипы',
        '🌌 Метафоры': 'метафоры', 
        '🧠 Самопознание': 'самопознание',
        '⚡ Конфликт': 'конфликт',
        '📋 Подготовка': 'подготовка',
        '🛡️ Возражения': 'возражения'
    }
    
    scenario_key = scenario_map.get(text)
    if scenario_key and scenario_key in DEMO_SCENARIOS[product]:
        demo_answer = DEMO_SCENARIOS[product][scenario_key]
        await update.message.reply_text(demo_answer)
        
        # Предлагаем выбрать еще
        keyboard = [
            [KeyboardButton("🎯 Другой сценарий")],
            [KeyboardButton("🔙 В меню")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Что дальше?", reply_markup=reply_markup)
        
    elif text == "🎯 Другой сценарий":
        await show_demo_scenarios(update, context, product)
        
    elif text == "🔙 В меню":
        bot_state.user_states[user.id] = 'PRODUCT_MENU'
        await show_product_menu(update, context, product)
        
    else:
        await update.message.reply_text("Выберите вариант из меню:")

def main():
    application = Application.builder().token(TOKEN).build()
    
    # Простые обработчики без ConversationHandler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
