import os
import logging
import asyncio
from typing import Dict, Any

# Импорты для AIOHTTP, HTTPX, и Reply Keyboard
import httpx 
from aiohttp import web

# Импорты для Reply Keyboard и Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
# ФИНАЛЬНЫЙ СТАБИЛЬНЫЙ ИМПОРТ: Импортируем Groq и APIError напрямую из основного пакета
from groq import Groq, APIError 
from telegram.constants import ParseMode

# ==============================================================================
# 0. КОНФИГУРАЦИЯ И ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ==============================================================================

# Настройка логирования
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение переменных окружения (ТОКЕНЫ)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") 
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") # URL вашего деплоя на Render

# Инициализация Groq клиента
groq_client: Groq | None = None
if GROQ_API_KEY:
    try:
        # Проверяем инициализацию, чтобы убедиться, что ключ корректен
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        logger.error(f"Ошибка инициализации Groq клиента: {e}")
else:
    logger.warning("GROQ_API_KEY не установлен. Функции AI будут недоступны.")

# ==============================================================================
# 1. МЕСТО ДЛЯ ВАШИХ ТЕКСТОВ И ПРОМТОВ
# ==============================================================================

# СЕКЦИЯ 1: ВСТАВЬТЕ СЮДА ВАШИ СИСТЕМНЫЕ ПРОМТЫ
SYSTEM_PROMPTS: Dict[str, str] = {
    'grimoire': "Действуй как таинственный Гримуар. Твоя задача — давать советы и наставления, используя метафорический, образный язык и древние аллегории. Не давай прямых ответов, но вдохновляй на поиск. Всегда начинай ответ с фразы 'О, искатель...' и заканчивай подписью '~ Страж Печати'.",
    'negotiator': "Ты — жесткий тренер по сложным переговорам. Твоя единственная цель — выявить слабые места в стратегии пользователя и заставить его думать глубже. Отвечай кратко, прямо, задавай провокационные вопросы, избегай похвалы и лишних эмоций. Сразу переходи к сути, требуя конкретики.",
    'analyzer': "Вы — старший финансовый аналитик с доступом к актуальным рыночным данным. Отвечайте строго по фактам, используйте только проверенную информацию и статистику. Избегайте предположений. Структурируйте ответ с заголовками: 'Текущая оценка', 'Ключевые риски', 'Прогноз'.",
    'coach': "Ты — энергичный, позитивный коуч по личной эффективности и продуктивности. Твоя задача — помочь пользователю структурировать цели, устранить прокрастинацию и создать четкий план действий. Используй мотивирующий, вдохновляющий тон.",
    'generator': "Ты — генератор прорывных бизнес-идей для стартапов. Всегда предлагай три уникальные, технологически-ориентированные идеи в ответ на запрос. Каждая идея должна включать: 'Название проекта', 'Проблема', 'Решение (Технология)', 'Целевая аудитория'.",
    'editor': "Ты — профессиональный редактор, специализирующийся на деловой и академической прозе. Твоя задача — исправлять грамматические, стилистические и пунктуационные ошибки в предоставленном тексте. Верни исходный текст с выделением всех изменений с помощью Markdown (**жирный** для добавлений, ~~зачеркнутый~~ для удалений) и добавь краткий комментарий о стиле.",
    'marketer': "Ты — эксперт по цифровому маркетингу и таргетированной рекламе. Предоставляй пользователю пошаговые стратегии продвижения. В ответе обязательно используй следующие блоки: 'Анализ ЦА', 'Каналы продвижения', 'KPI и метрики'.",
    'hr': "Ты — опытный HR-рекрутер, специализирующийся на IT-вакансиях. Твоя задача — помогать пользователю составлять резюме, проводить mock-интервью и оценивать соответствие кандидатов требованиям. Всегда давай оценку по 5-балльной шкале и указывай причины.",
}

# СЕКЦИЯ 2: ВСТАВЬТЕ СЮДА ВАШИ ДЛИННЫЕ ТЕКСТЫ ДЛЯ DEMO
DEMO_SCENARIOS: Dict[str, str] = {
    'grimoire': "🔮 **Гримуар** — это ваш мистический проводник в мире самопознания и принятия решений. Он не дает готовых ответов, но предлагает глубокие метафорические подсказки, которые помогут вам увидеть ситуацию под новым, неожиданным углом. Попробуйте спросить: 'Как мне поступить с новым проектом, который меня пугает?'",
    'negotiator': "🗣️ **Переговорщик** — это ваш персональный спарринг-партнер, который готовит вас к самым сложным сделкам. Он будет критиковать ваши предложения, находить уязвимости и требовать конкретных формулировок, чтобы вы вышли на переговоры полностью вооруженным. Попробуйте начать с фразы: 'Я хочу подготовиться к повышению зарплаты. Мой план...'",
    'analyzer': "📈 **Аналитик** — ваш надежный помощник в мире финансов и бизнеса. Он использует доступ к последней информации, чтобы предоставить вам объективную оценку рынка, акций или бизнес-идей. Он не дает советов, но предоставляет данные для принятия решений. Попробуйте спросить: 'Сводка по последнему квартальному отчету для Google и прогноз на следующий год'.",
    'coach': "🧘 **Коуч** поможет вам структурировать вашу личную жизнь и рабочие задачи. Он идеален для борьбы с прокрастинацией, установки реалистичных целей по методу SMART и разработки утренних ритуалов. Попробуйте сказать: 'Мне нужно начать бегать по утрам, но я не могу встать. Помоги составить план на неделю'.",
    'generator': "💡 **Генератор** — это креативный хаб для предпринимателей. Забудьте о стандартных идеях. Этот инструмент предлагает три прорывных концепции стартапов, основанных на последних технологических трендах (AI, Web3, биотехнологии). Попробуйте ввести: 'Идеи для стартапов, решающих проблему очередей в медицинских центрах'.",
    'editor': "📝 **Редактор** — ваш личный корректор и стилист. Он не только исправит все грамматические ошибки, но и улучшит структуру предложения, уберет канцеляризмы и сделает ваш текст более читаемым и убедительным. Он идеально подходит для деловой переписки, отчетов и студенческих работ. Попробуйте вставить любой текст с ошибками.",
    'marketer': "🎯 **Маркетолог** — ваш наставник в мире цифрового продвижения. Он разработает стратегию выхода на новую аудиторию, поможет определить ключевые KPI для рекламной кампании и выберет наиболее эффективные каналы продвижения. Попробуйте: 'Стратегия продвижения нового онлайн-курса по йоге для аудитории 45+'.",
    'hr': "🚀 **HR-рекрутер** помогает соискателям и нанимателям. Он может оценить ваше резюме, предложить вопросы для собеседования или дать оценку сильных и слабых сторон кандидата. Попробуйте: 'Оцени мое резюме (вставьте текст резюме) по позиции Senior Backend Developer'.",
}

# ==============================================================================
# 2. ФУНКЦИИ ГЕНЕРАЦИИ ТЕКСТА ЧЕРЕЗ GROQ
# ==============================================================================

async def handle_groq_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt_key: str):
    """Отправляет запрос в Groq, используя системный промт по ключу."""
    if not groq_client or not update.message:
        return

    user_query = update.message.text
    system_prompt = SYSTEM_PROMPTS.get(prompt_key, "Вы — полезный ассистент.")

    await update.message.chat.send_message(f"⌛ **{prompt_key.capitalize()}** обрабатывает ваш запрос...", parse_mode=ParseMode.MARKDOWN)

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]

        # ИСПРАВЛЕНИЕ: Используем актуальное имя модели Mixtral
        chat_completion = groq_client.chat.completions.create(
            messages=messages,
            model="mixtral-8x7b-instruct-v0.1" 
        )

        ai_response = chat_completion.choices[0].message.content

        await update.message.chat.send_message(
            f"**🤖 Ответ {prompt_key.capitalize()}:**\n\n{ai_response}",
            parse_mode=ParseMode.MARKDOWN
        )

    # Используем корректно импортированный класс APIError
    except APIError as e:
        logger.error(f"КОНКРЕТНАЯ ОШИБКА GROQ API (HTTP {e.status_code}): {e.body}")
        
        # Если это ошибка 429 (Rate Limit), сообщаем об этом
        if e.status_code == 429:
            user_message = "❌ **Превышен лимит запросов (Rate Limit Exceeded).** Пожалуйста, подождите минуту и попробуйте снова, или проверьте ваши лимиты в Groq Console."
        # Если это ошибка 400 (Bad Request - после фикса модели это может быть лимит или проблема с данными)
        elif e.status_code == 400:
            user_message = "❌ **Ошибка 400: Неверный запрос или лимиты.** Проверьте Groq Console. Возможно, превышен общий лимит токенов."
        # Если это ошибка 401 (Unauthorized - неверный ключ)
        elif e.status_code == 401:
            user_message = "❌ **Ошибка 401: Неверный API ключ Groq.** Убедитесь, что ваш ключ установлен правильно в Render."
        # Другие HTTP-ошибки
        else:
            user_message = f"❌ **Ошибка Groq API:** Проблема с сервисом или лимитами. Код ошибки: {e.status_code}."
            
        await update.message.chat.send_message(
            user_message,
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Неизвестная ошибка при работе с Groq API: {e}")
        # Fallback к общему сообщению
        await update.message.chat.send_message(
            "Произошла ошибка при обращении к AI. Проверьте ваш API ключ Groq или попробуйте позже.",
            parse_mode=ParseMode.MARKDOWN
        )

# ==============================================================================
# 3. ВСЕ ОСТАЛЬНЫЕ ФУНКЦИИ (ВАША ЛОГИКА)
# ==============================================================================

# Константы для состояний
STATE_MAIN_MENU = 0
STATE_BUSINESS_MENU = 2
STATE_AI_SELECTION = 3
STATE_CALCULATOR = 5

# Создание постоянной клавиатуры (Reply Keyboard)
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("/start"), KeyboardButton("/menu")]], 
    one_time_keyboard=False, 
    resize_keyboard=True
)


# --- Общие Хендлеры и Меню ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает команду /start и выводит главное меню, а также Reply Keyboard."""
    if not update.message: 
        return STATE_MAIN_MENU

    inline_keyboard = [
        [InlineKeyboardButton("Для себя (ИИ-инструменты)", callback_data='menu_self')],
        [InlineKeyboardButton("Для дела (Калькуляторы и ИИ-инструменты)", callback_data='menu_business')]
    ]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    # Отправляем сообщение с Inline Keyboards И прикрепляем Reply Keyboard
    await update.message.reply_text(
        "👋 Привет! Используйте нижнюю панель для навигации.", 
        reply_markup=REPLY_KEYBOARD, 
        reply_to_message_id=update.message.message_id
    )
    # Отправляем Inline Keyboard в отдельном сообщении или редактируем (тут лучше отдельное)
    await update.message.reply_text(
        "Выберите инструмент:",
        reply_markup=inline_markup
    )
    
    context.user_data['state'] = STATE_MAIN_MENU
    context.user_data['active_groq_mode'] = None
    return STATE_MAIN_MENU

# Добавляем хендлер для /menu, который делает то же, что и /start
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает команду /menu, которая является синонимом /start."""
    # Просто вызываем start
    return await start(update, context)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выводит главное меню после нажатия кнопки 'В главное меню' (из Callback Query)."""
    query = update.callback_query
    if query:
        await query.answer()
        keyboard = [
            [InlineKeyboardButton("Для себя (ИИ-инструменты)", callback_data='menu_self')],
            [InlineKeyboardButton("Для дела (Калькуляторы и ИИ-инструменты)", callback_data='menu_business')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("👋 Выберите раздел:", reply_markup=reply_markup)
        context.user_data['state'] = STATE_MAIN_MENU
        context.user_data['active_groq_mode'] = None
    return STATE_MAIN_MENU

# --- Меню "Для себя" ---

async def menu_self(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор 'Для себя' и выводит меню выбора AI."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🔮 Гримуар", callback_data='ai_grimoire_self'), 
         InlineKeyboardButton("📈 Аналитик", callback_data='ai_analyzer_self')],
        [InlineKeyboardButton("🧘 Коуч", callback_data='ai_coach_self'), 
         InlineKeyboardButton("💡 Генератор", callback_data='ai_generator_self')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("Вы выбрали *Для себя*. Выберите ИИ-инструмент:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    context.user_data['state'] = STATE_AI_SELECTION
    context.user_data['active_groq_mode'] = None
    return STATE_AI_SELECTION

# --- Меню "Для дела" ---

async def menu_business(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор 'Для дела' и выводит меню выбора AI/Калькулятора."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Калькулятор маркетплейсов", callback_data='menu_calculator')],
        [InlineKeyboardButton("🗣️ Переговорщик", callback_data='ai_negotiator_business'), 
         InlineKeyboardButton("📝 Редактор", callback_data='ai_editor_business')],
        [InlineKeyboardButton("🎯 Маркетолог", callback_data='ai_marketer_business'), 
         InlineKeyboardButton("🚀 HR-рекрутер", callback_data='ai_hr_business')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("Вы выбрали *Для дела*. Выберите инструмент:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    context.user_data['state'] = STATE_BUSINESS_MENU
    context.user_data['active_groq_mode'] = None
    return STATE_BUSINESS_MENU

# --- Обработка выбора AI ---

def get_ai_keyboard(prompt_key: str, back_button: str) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для выбранного AI с демо-сценарием и платным доступом."""
    keyboard = [
        [InlineKeyboardButton("💡 Демо-сценарий (что он умеет?)", callback_data=f'demo_{prompt_key}')],
        [InlineKeyboardButton("✅ Активировать платный доступ (10 кнопок)", callback_data=f'activate_{prompt_key}')],
        [InlineKeyboardButton("🔙 Назад", callback_data=back_button)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def ai_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор конкретного AI и предлагает демо или активацию."""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    # Получаем ключ промта: 'ai_grimoire_self' -> 'grimoire'
    prompt_key = callback_data.split('_')[1] 

    context.user_data['current_ai_key'] = prompt_key
    
    if callback_data.endswith('_self'):
        back_button = 'menu_self'
    else:
        back_button = 'menu_business'
        
    reply_markup = get_ai_keyboard(prompt_key, back_button)

    await query.edit_message_text(
        f"Вы выбрали **{prompt_key.capitalize()}**.\n\n"
        f"Чтобы начать, изучите демо-сценарий или активируйте доступ.", 
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['state'] = STATE_AI_SELECTION
    context.user_data['active_groq_mode'] = None
    return STATE_AI_SELECTION

async def show_demo_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выводит длинный текст демо-сценария для выбранного AI."""
    query = update.callback_query
    await query.answer()
    
    # Ключ демо-сценария совпадает с ключом промта (например, 'demo_grimoire' -> 'grimoire')
    demo_key = query.data.split('_')[1] 
    
    # Используем заполненные промты
    text_content = DEMO_SCENARIOS.get(demo_key, "⚠️ Описание демо-сценария не найдено. Проверьте ваш словарь DEMO_SCENARIOS.")
    
    # Определяем меню по предыдущему состоянию
    back_to_menu_key = 'menu_self' 
    if context.user_data.get('state') == STATE_BUSINESS_MENU:
        back_to_menu_key = 'menu_business'
    
    keyboard = [[InlineKeyboardButton("🔙 Назад к выбору AI", callback_data=back_to_menu_key)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text_content, 
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    # Возвращаемся в меню выбора (для себя или для бизнеса)
    context.user_data['state'] = STATE_AI_SELECTION if back_to_menu_key == 'menu_self' else STATE_BUSINESS_MENU
    return context.user_data['state']

async def activate_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает активацию платного доступа. 
    Меняет состояние, чтобы следующие сообщения отправлялись в Groq с нужным промтом.
    """
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ключ AI (например, 'activate_grimoire' -> 'grimoire')
    prompt_key = query.data.split('_')[1]
    
    # Сохраняем текущий активный AI-ключ для обработки текстовых сообщений
    context.user_data['active_groq_mode'] = prompt_key
    
    # Убираем инлайн-клавиатуру и переходим в режим ожидания текста
    await query.edit_message_text(
        f"✅ Режим **{prompt_key.capitalize()}** активирован!\n\n"
        f"Напишите ваш первый запрос, и {prompt_key.capitalize()} приступит к работе.\n\n"
        f"Чтобы сменить режим, используйте команду /menu (она есть на нижней панели).", 
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data['state'] = STATE_AI_SELECTION # Состояние остается в AI-режиме
    return context.user_data['state']


# --- Калькулятор Маркетплейсов (STATE_CALCULATOR) ---

async def menu_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает режим калькулятора."""
    query = update.callback_query
    await query.answer()

    context.user_data['calc_data'] = {}
    context.user_data['calc_step'] = 0
    context.user_data['active_groq_mode'] = None
    
    await query.edit_message_text("🔢 **Калькулятор маркетплейсов**\n\nВведите закупочную цену товара в рублях:", parse_mode=ParseMode.MARKDOWN)
    context.user_data['state'] = STATE_CALCULATOR
    return STATE_CALCULATOR

async def handle_calculator_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает шаги калькулятора."""
    if not update.message: return STATE_CALCULATOR
    message_text = update.message.text
    step = context.user_data.get('calc_step', 0)

    try:
        # Универсальная обработка ввода чисел
        value = float(message_text.replace(',', '.').strip())
        calc_data = context.user_data.get('calc_data', {})

        if step == 0:
            calc_data['purchase_price'] = value
            context.user_data['calc_step'] = 1
            await update.message.reply_text("Введите процент комиссии маркетплейса (например, 15):")
        
        elif step == 1:
            calc_data['commission_percent'] = value
            context.user_data['calc_step'] = 2
            await update.message.reply_text("Введите желаемую цену продажи на маркетплейсе (в рублях):")
            
        elif step == 2:
            calc_data['sale_price'] = value
            context.user_data['calc_step'] = 3
            await update.message.reply_text("Введите фиксированные расходы на логистику и хранение (в рублях):")
            
        elif step == 3:
            calc_data['logistics_cost'] = value
            context.user_data['calc_step'] = 4 
            
            # --- РАСЧЕТ ---
            purchase_price = calc_data['purchase_price']
            commission_percent = calc_data['commission_percent']
            sale_price = calc_data['sale_price']
            logistics_cost = calc_data['logistics_cost']
            
            commission_cost = sale_price * (commission_percent / 100)
            net_profit = sale_price - purchase_price - commission_cost - logistics_cost
            
            if purchase_price > 0:
                roi = (net_profit / purchase_price) * 100
            else:
                roi = 0

            # --- ВЫВОД РЕЗУЛЬТАТОВ ---
            result_text = (
                "✅ **Результаты расчёта:**\n\n"
                f"💰 Цена продажи: *{sale_price:.2f} ₽*\n"
                f"🛒 Закупочная цена: *{purchase_price:.2f} ₽*\n"
                f"📉 Комиссия ({commission_percent}%): *{commission_cost:.2f} ₽*\n"
                f"🚚 Логистика/Хранение: *{logistics_cost:.2f} ₽*\n"
                "---------------------------------\n"
                f"**🟢 Чистая прибыль:** **{net_profit:.2f} ₽**\n"
                f"**📈 Рентабельность (ROI):** **{roi:.2f}%**\n\n"
            )
            
            if roi < 15:
                result_text += "⚠️ **Внимание:** Рентабельность ниже рекомендуемой."
            elif roi >= 15 and roi < 30:
                result_text += "👍 **Отлично:** Хорошая рентабельность."
            else:
                result_text += "🚀 **Супер:** Высокая рентабельность!"
                
            keyboard = [[InlineKeyboardButton("🔙 Назад в меню 'Для дела'", callback_data='menu_business')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            context.user_data['state'] = STATE_BUSINESS_MENU
            context.user_data['calc_step'] = 0
            return STATE_BUSINESS_MENU

    except ValueError:
        await update.message.reply_text("❌ Ошибка ввода. Пожалуйста, введите число (можно с точкой или запятой).")
        return STATE_CALCULATOR

    except Exception as e:
        logger.error(f"Ошибка калькулятора: {e}")
        await update.message.reply_text("Произошла неожиданная ошибка в калькуляторе. Начните заново командой /start.")
        context.user_data['state'] = STATE_MAIN_MENU
        return STATE_MAIN_MENU

# --- Обработка всех остальных текстовых сообщений ---

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Единый хендлер для всех текстовых сообщений. 
    Перенаправляет сообщения либо в калькулятор, либо в Groq, либо выводит ошибку.
    """
    current_state = context.user_data.get('state', STATE_MAIN_MENU)
    
    if current_state == STATE_CALCULATOR:
        return await handle_calculator_input(update, context)
        
    elif context.user_data.get('active_groq_mode'):
        active_mode = context.user_data['active_groq_mode']
        # Проверяем, что AI режим активирован
        if active_mode in SYSTEM_PROMPTS:
            # Вызываем функцию Groq
            return await handle_groq_request(update, context, active_mode)
        else:
            await update.message.reply_text("❓ Неизвестный AI режим. Нажмите /start для сброса.")
            return STATE_MAIN_MENU

    
    elif current_state in (STATE_AI_SELECTION, STATE_BUSINESS_MENU):
        await update.message.reply_text("❓ Вы отправили текст, но не активировали ни один из ИИ-инструментов. Нажмите на кнопку 'Активировать' под нужным инструментом, чтобы начать диалог, или /start для возврата в главное меню.")
        return current_state
    
    else:
        await update.message.reply_text("🤔 Не понимаю. Выберите действие из меню или используйте /start, чтобы начать заново.")
        return current_state

# ==============================================================================
# 4. НАСТРОЙКА И ЗАПУСК БОТА (WEBHOOK/RENDER)
# ==============================================================================

if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN не установлен. Запуск невозможен.")
    application = None
else:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Подключение хендлеров
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command)) 
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(menu_self, pattern='^menu_self$'))
    application.add_handler(CallbackQueryHandler(menu_business, pattern='^menu_business$'))
    application.add_handler(CallbackQueryHandler(menu_calculator, pattern='^menu_calculator$'))
    application.add_handler(CallbackQueryHandler(ai_selection_handler, pattern='^ai_.*_self$|^ai_.*_business$'))
    application.add_handler(CallbackQueryHandler(show_demo_scenario, pattern='^demo_.*$'))
    application.add_handler(CallbackQueryHandler(activate_access, pattern='^activate_.*$'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

# --- AIOHTTP HANDLER ---
async def telegram_webhook_handler(request: web.Request) -> web.Response:
    """Обрабатывает входящие запросы от Telegram и передает их PTB."""
    global application
    if application is None:
        return web.Response(status=500, text="Application not initialized.")
    
    # Получаем тело запроса
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    # Передаем обновление в python-telegram-bot
    update = Update.de_json(data, application.bot)
    # Используем process_update для обработки без конфликтов циклов
    await application.process_update(update)

    # Telegram ожидает HTTP 200 OK как подтверждение получения
    return web.Response(text="OK")


async def init_webhook_and_start_server(application: Application):
    """Устанавливает webhook и запускает AIOHTTP сервер."""
    if not os.environ.get('PORT') or not WEBHOOK_URL:
        logger.error("❌ Недостаточно переменных окружения (PORT или WEBHOOK_URL) для Webhook.")
        return

    webhook_path = "/"
    full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
    
    # 1. Установка Webhook через HTTPX (внешний клиент)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
            json={"url": full_webhook_url}
        )
        if response.status_code == 200 and response.json().get('ok'):
            logger.info(f"✅ Webhook успешно установлен: {full_webhook_url}")
        else:
            logger.error(f"❌ Ошибка установки Webhook: {response.text}")
            return


    # 2. Запуск AIOHTTP сервера
    # ИСПРАВЛЕННАЯ ЛОГИКА МАРШРУТИЗАЦИИ:
    app = web.Application()
    app.add_routes([
        web.post(webhook_path, telegram_webhook_handler),
    ])
    
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    site = web.TCPSite(app_runner, '0.0.0.0', PORT)
    
    logger.info(f"🚀 AIOHTTP Server запущен на порту {PORT}")
    
    # Запускаем Application для инициализации внутренних структур PTB
    await application.initialize()
    
    await site.start()

    # Ожидаем завершения (чтобы процесс Render не завершился сразу)
    await asyncio.Future() 


if __name__ == '__main__':
    if TELEGRAM_TOKEN and os.environ.get('PORT') and application:
        try:
            # Использование asyncio.run для запуска aiohttp сервера
            asyncio.run(init_webhook_and_start_server(application))
        except KeyboardInterrupt:
            logger.info("Бот остановлен вручную.")
        except Exception as e:
            logger.error(f"Критическая ошибка при запуске бота: {e}")
