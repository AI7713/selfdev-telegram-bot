import os
import logging
import random
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_TOKEN')

# ЗАЩИЩЕННЫЕ демо-сценарии без раскрытия логики промтов
DEMO_SCENARIOS = {
    'гримуар': {
        'архетипы': '🔮 Платная версия предоставляет персонализированный анализ ваших внутренних паттернов и практические рекомендации для повседневного применения.',
        'метафоры': '🌌 Полный доступ открывает глубокую работу с образами и символами для трансформации восприятия жизненных ситуаций.',
        'самопознание': '🧠 В платной версии вы получаете ежедневные инсайты и персонализированные практики для последовательного развития.'
    },
    'переговорщик': {
        'конфликт': '⚡ Полный доступ включает работу со сложными диалогами, включая техники управления эмоциями и структурирования беседы.',
        'подготовка': '📋 Платная версия предоставляет системный подход к подготовке, включая анализ всех участников и возможных сценариев.',
        'возражения': '🛡️ В платной версии вы освоите различные подходы к работе с сопротивлением и научитесь превращать возражения в возможности.'
    },
    'проекты': {
        'формулировка': '🚀 Полный доступ включает углубленную работу над идеей с привлечением экспертных оценок и проверкой жизнеспособности.',
        'планирование': '📊 Платная версия предоставляет комплексное планирование с распределением ролей, сроков и критериев успеха.',
        'исполнение': '⚡ В платной версии вы получаете пошаговое сопровождение с проверкой результатов на каждом этапе.'
    },
    'карта личности': {
        'профиль': '🧠 Полный доступ включает расширенную диагностику ваших особенностей с учетом множества факторов и контекстов.',
        'сильные стороны': '💪 Платная версия помогает идентифицировать ваши уникальные преимущества и области для осознанного развития.',
        'сценарии': '📈 В платной версии вы получаете персонализированные дорожные карты развития с учетом ваших целей и возможностей.'
    },
    'стратегия': {
        'анализ': '📈 Полный доступ предоставляет углубленный анализ темы с учетом множества факторов и перспектив развития.',
        'применение': '🎯 Платная версия включает разработку конкретных шагов и тактик для реализации выбранного направления.',
        'прогноз': '🔮 В платной версии вы получаете сценарное планирование с оценкой рисков и возможностей.'
    },
    'дайджест': {
        'обзор': '🌍 Полный доступ включает регулярные обзоры ключевых метрик и событий с профессиональным анализом.',
        'прогнозы': '📊 Платная версия предоставляет прогнозы развития ситуации с указанием вероятностей и факторов влияния.',
        'рекомендации': '💡 В платной версии вы получаете персонализированные рекомендации, учитывающие вашу специфику и цели.'
    },
    'маркетплейс': {
        'экономика': '🛒 Полный доступ включает комплексный расчет финансовых показателей с учетом различных сценариев.',
        'карточка': '📋 Платная версия помогает создавать эффективные товарные карточки с учетом поведенческих факторов.',
        'продвижение': '🚀 В платной версии вы получаете стратегии привлечения внимания и удержания интереса аудитории.'
    },
    'анализ итогов': {
        'причины': '🔍 Полный доступ включает глубокий анализ достигнутых результатов и факторов, повлиявших на исход.',
        'данные': '📊 Платная версия предоставляет работу с различными типами данных и их интерпретацию в вашем контексте.',
        'обратный план': '🔄 В платной версии вы восстанавливаете успешную последовательность действий для повторения результата.'
    },
    'компас тем': {
        'мотивы': '🧭 Полный доступ включает исследование глубинных причин интереса к теме и их согласованности с ценностями.',
        'исход': '🎯 Платная версия помогает формулировать измеримые цели и определять желаемые результаты.',
        'эксперимент': '⚡ В платной версии вы создаете безопасные условия для проверки гипотез и получения обратной связи.'
    },
    'макро-анализ': {
        'метрики': '📊 Полный доступ включает мониторинг ключевых показателей с профессиональной интерпретацией их динамики.',
        'сценарии': '🌐 Платная версия предоставляет разработку сценариев развития с учетом множества переменных.',
        'действия': '💡 В платной версии вы получаете конкретные рекомендации для разных временных горизонтов.'
    }
}

# Каталог всех инструментов
PROMPTS_CATALOG = {
    'Гримуар': {
        'описание': '🎯 Фокус и снижение шума за 5-10 минут',
        'для_чего': 'Помогает вернуть ясность ума и выбрать 1-3 конкретных шага для движения вперед',
        'кнопка': '🔮 Гримуар',
        'категория': 'self',
        'демо_ключ': 'гримуар'
    },
    'Переговорщик': {
        'описание': '💼 Тренажёр переговоров с разбором методов', 
        'для_чего': 'Отработка сложных диалогов в режимах: телефон, почта, встречи, семья',
        'кнопка': '💼 Переговорщик',
        'категория': 'business',
        'демо_ключ': 'переговорщик'
    },
    'Оркестратор проекта': {
        'описание': '🚀 От идеи к плану и исполнению',
        'для_чего': 'Создание проектов с четкими этапами, сроками и распределением ролей',
        'кнопка': '📋 Проекты',
        'категория': 'business',
        'демо_ключ': 'проекты'
    },
    'Карта личности': {
        'описание': '🧠 Ваш психологический профиль и рост',
        'для_чего': 'Определяет сильные стороны, архетипы и создает персонализированные планы развития',
        'кнопка': '🧩 Моя карта',
        'категория': 'self',
        'демо_ключ': 'карта личности'
    },
    'Стратегический анализ': {
        'описание': '📈 Глубокий разбор тем и рынков',
        'для_чего': 'Анализ трендов, разработка KPI и стратегий выхода на рынок',
        'кнопка': '🎯 Стратегия',
        'категория': 'business',
        'демо_ключ': 'стратегия'
    },
    'Еженедельный дайджест': {
        'описание': '🌍 Обзор мира + прогнозы',
        'для_чего': 'Актуальные метрики, сценарии развития и персональные рекомендации',
        'кнопка': '📊 Дайджест',
        'категория': 'self',
        'демо_ключ': 'дайджест'
    },
    'Запуск на маркетплейсе': {
        'описание': '🛒 От экономики до продвижения',
        'для_чего': 'Расчет маржи, создание карточек товара и стратегии роста продаж',
        'кнопка': '🛍️ Маркетплейс',
        'категория': 'business',
        'демо_ключ': 'маркетплейс'
    },
    'Анализ результатов': {
        'описание': '🔍 От итога к причинам успеха',
        'для_чего': 'Разбор достигнутых результатов и восстановление успешной траектории',
        'кнопка': '📐 Анализ итогов',
        'категория': 'business',
        'демо_ключ': 'анализ итогов'
    },
    'Компас тем': {
        'описание': '🧭 Навигатор выбора направления',
        'для_чего': 'Определение мотивов, постановка KPI и выбор безопасного первого шага',
        'кнопка': '🧭 Компас тем',
        'категория': 'self',
        'демо_ключ': 'компас тем'
    },
    'Макро-сценарии': {
        'описание': '📊 Экономика → ваши действия',
        'для_чего': 'Сценарии на 6-36 месяцев и принятие персональных решений',
        'кнопка': '🌐 Макро-анализ',
        'категория': 'business',
        'демо_ключ': 'макро-анализ'
    }
}

# Маппинг красивых названий кнопок для демо-сценариев
DEMO_BUTTON_NAMES = {
    'архетипы': '🔮 Архетипы',
    'метафоры': '🌌 Метафоры',
    'самопознание': '🧠 Самопознание',
    'конфликт': '⚡ Конфликт',
    'подготовка': '📋 Подготовка',
    'возражения': '🛡️ Возражения',
    'формулировка': '🎯 Формулировка',
    'планирование': '📊 Планирование',
    'исполнение': '⚡ Исполнение',
    'профиль': '🧠 Профиль',
    'сильные стороны': '💪 Сильные стороны',
    'сценарии': '📈 Сценарии роста',
    'анализ': '📈 Анализ',
    'применение': '🎯 Применение',
    'прогноз': '🔮 Прогноз',
    'обзор': '🌍 Обзор',
    'прогнозы': '📊 Прогнозы',
    'рекомендации': '💡 Рекомендации',
    'экономика': '🛒 Экономика',
    'карточка': '📋 Карточка',
    'продвижение': '🚀 Продвижение',
    'причины': '🔍 Причины',
    'данные': '📊 Данные',
    'обратный план': '🔄 Обратный план',
    'мотивы': '🧭 Мотивы',
    'исход': '🎯 Исход',
    'эксперимент': '⚡ Эксперимент',
    'метрики': '📊 Метрики',
    'сценарии_макро': '🌐 Сценарии',
    'действия': '💡 Действия'
}

class BotState:
    def __init__(self):
        self.user_states = {}

bot_state = BotState()

async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    logger.info(f"Пользователь {user.first_name} начал работу")
    
    bot_state.user_states[user.id] = 'MAIN_MENU'
    
    keyboard = [
        [KeyboardButton("🧠 ДЛЯ СЕБЯ"), KeyboardButton("🚀 ДЛЯ ДЕЛА")],
        [KeyboardButton("📚 ВСЕ ИНСТРУМЕНТЫ"), KeyboardButton("ℹ️ О БОТЕ")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🛠️ **Добро пожаловать в платформу саморазвития!**\n\n"
        "Выберите категорию инструментов:",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    current_state = bot_state.user_states.get(user.id, 'MAIN_MENU')
    
    if current_state == 'MAIN_MENU':
        await handle_main_menu(update, context)
    elif current_state == 'CATEGORY_MENU':
        await handle_category_menu(update, context)
    elif current_state == 'TOOL_MENU':
        await handle_tool_menu(update, context)
    elif current_state == 'DEMO_MENU':
        await handle_demo_menu(update, context)

async def handle_main_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    
    if text == "🧠 ДЛЯ СЕБЯ":
        bot_state.user_states[user.id] = 'CATEGORY_MENU'
        context.user_data['current_category'] = 'self'
        await show_self_category(update, context)
        
    elif text == "🚀 ДЛЯ ДЕЛА":
        bot_state.user_states[user.id] = 'CATEGORY_MENU'
        context.user_data['current_category'] = 'business'
        await show_business_category(update, context)
        
    elif text == "📚 ВСЕ ИНСТРУМЕНТЫ":
        bot_state.user_states[user.id] = 'CATEGORY_MENU'
        context.user_data['current_category'] = 'all'
        await show_all_tools(update, context)
        
    elif text == "ℹ️ О БОТЕ":
        await update.message.reply_text(
            "🤖 **Платформа саморазвития и профессионального роста**\n\n"
            "🔮 **Гримуар** - фокус и самопознание через метафоры\n"
            "💼 **Переговорщик** - навыки сложных диалогов\n"
            "📋 **Проекты** - от идеи к исполнению\n"
            "🧩 **Моя карта** - психологический профиль и рост\n"
            "🎯 **Стратегия** - анализ рынков и трендов\n"
            "📊 **Дайджест** - обзоры и прогнозы\n"
            "🛍️ **Маркетплейс** - запуск и рост продаж\n"
            "📐 **Анализ итогов** - разбор успехов\n"
            "🧭 **Компас тем** - выбор направления\n"
            "🌐 **Макро-анализ** - экономика и решения\n\n"
            "Каждый инструмент имеет демо-версию и готов к платному доступу!"
        )
    else:
        await update.message.reply_text("Выберите категорию из меню:")

async def show_self_category(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [KeyboardButton("🔮 Гримуар"), KeyboardButton("🧩 Моя карта")],
        [KeyboardButton("🧭 Компас тем"), KeyboardButton("📊 Дайджест")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🧠 **ДЛЯ СЕБЯ**\n\n"
        "Инструменты для личного роста и самопознания:",
        reply_markup=reply_markup
    )

async def show_business_category(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [KeyboardButton("💼 Переговорщик"), KeyboardButton("📋 Проекты")],
        [KeyboardButton("🎯 Стратегия"), KeyboardButton("🛍️ Маркетплейс")],
        [KeyboardButton("📐 Анализ итогов"), KeyboardButton("🌐 Макро-анализ")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🚀 **ДЛЯ ДЕЛА**\n\n"
        "Инструменты для профессионального роста и бизнеса:",
        reply_markup=reply_markup
    )

async def show_all_tools(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [KeyboardButton("🔮 Гримуар"), KeyboardButton("💼 Переговорщик")],
        [KeyboardButton("📋 Проекты"), KeyboardButton("🧩 Моя карта")],
        [KeyboardButton("🎯 Стратегия"), KeyboardButton("📊 Дайджест")],
        [KeyboardButton("🛍️ Маркетплейс"), KeyboardButton("📐 Анализ итогов")],
        [KeyboardButton("🧭 Компас тем"), KeyboardButton("🌐 Макро-анализ")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📚 **ВСЕ ИНСТРУМЕНТЫ**\n\n"
        "Полный каталог доступных возможностей:",
        reply_markup=reply_markup
    )

async def handle_category_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    
    if text == "🔙 Назад":
        bot_state.user_states[user.id] = 'MAIN_MENU'
        await start(update, context)
        return
    
    # Маппинг кнопок на инструменты
    tool_mapping = {
        '🔮 Гримуар': 'Гримуар',
        '💼 Переговорщик': 'Переговорщик',
        '📋 Проекты': 'Оркестратор проекта',
        '🧩 Моя карта': 'Карта личности',
        '🎯 Стратегия': 'Стратегический анализ',
        '📊 Дайджест': 'Еженедельный дайджест',
        '🛍️ Маркетплейс': 'Запуск на маркетплейсе',
        '📐 Анализ итогов': 'Анализ результатов',
        '🧭 Компас тем': 'Компас тем',
        '🌐 Макро-анализ': 'Макро-сценарии'
    }
    
    if text in tool_mapping:
        tool_name = tool_mapping[text]
        bot_state.user_states[user.id] = 'TOOL_MENU'
        context.user_data['current_tool'] = tool_name
        await show_tool_description(update, context, tool_name)
    else:
        await update.message.reply_text("Выберите инструмент из меню:")

async def show_tool_description(update: Update, context: CallbackContext, tool_name: str) -> None:
    tool_data = PROMPTS_CATALOG[tool_name]
    
    # Для ВСЕХ инструментов есть кнопки демо/платно
    keyboard = [
        [KeyboardButton("🆓 Попробовать"), KeyboardButton("💳 Платный доступ")],
        [KeyboardButton("🔙 Назад")]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"**{tool_data['кнопка']}**\n\n"
        f"{tool_data['описание']}\n\n"
        f"🎯 {tool_data['для_чего']}",
        reply_markup=reply_markup
    )

async def handle_tool_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    tool_name = context.user_data.get('current_tool', 'unknown')
    category = context.user_data.get('current_category', 'all')
    
    if text == "🔙 Назад":
        bot_state.user_states[user.id] = 'CATEGORY_MENU'
        if category == 'self':
            await show_self_category(update, context)
        elif category == 'business':
            await show_business_category(update, context)
        else:
            await show_all_tools(update, context)
        return
    
    if text == "🆓 Попробовать":
        # Для всех инструментов есть демо
        if tool_name in PROMPTS_CATALOG:
            bot_state.user_states[user.id] = 'DEMO_MENU'
            demo_key = PROMPTS_CATALOG[tool_name]['демо_ключ']
            context.user_data['current_product'] = demo_key
            context.user_data['current_tool_for_demo'] = tool_name
            await show_demo_scenarios(update, context, demo_key)
    
    elif text == "💳 Платный доступ":
        await update.message.reply_text(
            "🚀 **Платный доступ откроет:**\n\n"
            "• Живое общение с AI-помощником\n"
            "• Персонализированные ответы на ваши вопросы\n" 
            "• Полный функционал инструмента\n"
            "• Доступ на 5 дней\n\n"
            "Скоро здесь можно будет приобрести доступ!"
        )

async def show_demo_scenarios(update: Update, context: CallbackContext, product: str) -> None:
    scenarios = DEMO_SCENARIOS[product]
    
    # Создаем клавиатуру на основе доступных сценариев
    keyboard = []
    for scenario_name in scenarios.keys():
        button_text = DEMO_BUTTON_NAMES.get(scenario_name, scenario_name)
        keyboard.append([KeyboardButton(button_text)])
    
    keyboard.append([KeyboardButton("🔙 Назад")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Выберите аспект для демо-знакомства:",
        reply_markup=reply_markup
    )

async def handle_demo_menu(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    text = update.message.text
    product = context.user_data.get('current_product', 'unknown')
    tool_name = context.user_data.get('current_tool_for_demo', 'unknown')
    
    if text == "🔙 Назад":
        bot_state.user_states[user.id] = 'TOOL_MENU'
        await show_tool_description(update, context, tool_name)
        return
    
    # Обратный маппинг для обработки выбора сценария
    reverse_button_mapping = {v: k for k, v in DEMO_BUTTON_NAMES.items()}
    scenario_key = reverse_button_mapping.get(text)
    
    if scenario_key and scenario_key in DEMO_SCENARIOS[product]:
        demo_answer = DEMO_SCENARIOS[product][scenario_key]
        await update.message.reply_text(demo_answer)
        
        keyboard = [
            [KeyboardButton("🎯 Другой сценарий")],
            [KeyboardButton("🔙 В меню инструмента")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Что дальше?", reply_markup=reply_markup)
        
    elif text == "🎯 Другой сценарий":
        await show_demo_scenarios(update, context, product)
        
    elif text == "🔙 В меню инструмента":
        bot_state.user_states[user.id] = 'TOOL_MENU'
        await show_tool_description(update, context, tool_name)
        
    else:
        await update.message.reply_text("Выберите вариант из меню:")

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен с защищенной структурой демо-описаний!")
    application.run_polling()

if __name__ == '__main__':
    main()
