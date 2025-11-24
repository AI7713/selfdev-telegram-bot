import os
import logging
import asyncio
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq
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
# Render предоставляет порт через переменную PORT, используем ее.
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
# 1. МЕСТО ДЛЯ ВАШИХ ТЕКСТОВ И ПРОМТОВ (ОБНОВИТЕ ЭТИ ДВЕ СЕКЦИИ!)
# ==============================================================================

# СЕКЦИЯ 1: ВСТАВЬТЕ СЮДА ВАШИ СИСТЕМНЫЕ ПРОМТЫ
SYSTEM_PROMPTS: Dict[str, str] = {
    'grimoire': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_ГРИМУАРА: Действуй как мистический помощник, используй образное и метафорическое описание...",
    'negotiator': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_ПЕРЕГОВОРЩИКА: Ты жесткий, требовательный тренер по переговорам. Отвечай кратко, без лишних эмоций, сразу переходи к сути...",
    'analyzer': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_АНАЛИТИКА: Ты финансовый аналитик с доступом к последним рыночным данным. Отвечай строго по фактам, используя только проверенную информацию.",
    'coach': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_КОУЧА",
    'generator': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_ГЕНЕРАТОРА",
    'editor': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_РЕДАКТОРА",
    'marketer': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_МАРКЕТОЛОГА",
    'hr': "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ_ДЛЯ_HR-РЕКРУТЕРА",
}

# СЕКЦИЯ 2: ВСТАВЬТЕ СЮДА ВАШИ ДЛИННЫЕ ТЕКСТЫ ДЛЯ DEMO
DEMO_SCENARIOS: Dict[str, str] = {
    'grimoire': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_ГРИМУАРА. (Полный текст)",
    'negotiator': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_ПЕРЕГОВОРЩИКА. (Полный текст)",
    'analyzer': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_АНАЛИТИКА. (Полный текст)",
    'coach': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_КОУЧА. (Полный текст)",
    'generator': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_ГЕНЕРАТОРА. (Полный текст)",
    'editor': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_РЕДАКТОРА. (Полный текст)",
    'marketer': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_МАРКЕТОЛОГА. (Полный текст)",
    'hr': "ВСТАВЬТЕ_СЮДА_ДЛИННОЕ_ОПИСАНИЕ_ДЕМО_ДЛЯ_HR-РЕКРУТЕРА. (Полный текст)",
}

# ==============================================================================
# 2. ФУНКЦИИ ГЕНЕРАЦИИ ТЕКСТА ЧЕРЕЗ GROQ
# ==============================================================================

async def handle_groq_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt_key: str):
    """Отправляет запрос в Groq, используя системный промт по ключу."""
    if not groq_client or not update.message:
        return

    # Проверка, что промты заполнены, иначе выводим ошибку
    if "ВСТАВЬТЕ_СЮДА_ВАШ_ПРОМТ" in SYSTEM_PROMPTS.get(prompt_key, ""):
        await update.message.chat.send_message(
            "⚠️ **Внимание:** Ваши системные промты еще не заполнены в коде `main.py`! Пожалуйста, обновите файл на GitHub, прежде чем использовать AI.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    user_query = update.message.text
    system_prompt = SYSTEM_PROMPTS.get(prompt_key, "Вы — полезный ассистент.")

    await update.message.chat.send_message(f"⌛ **{prompt_key.capitalize()}** обрабатывает ваш запрос...", parse_mode=ParseMode.MARKDOWN)

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]

        # Используем модель Llama 3 8B, быструю и эффективную
        chat_completion = groq_client.chat.completions.create(
            messages=messages,
            model="llama3-8b-8192"
        )

        ai_response = chat_completion.choices[0].message.content

        await update.message.chat.send_message(
            f"**🤖 Ответ {prompt_key.capitalize()}:**\n\n{ai_response}",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Ошибка при работе с Groq API: {e}")
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

# --- Общие Хендлеры и Меню ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает команду /start и выводит главное меню."""
    if not update.message: 
        return STATE_MAIN_MENU

    keyboard = [
        [InlineKeyboardButton("Для себя (ИИ-инструменты)", callback_data='menu_self')],
        [InlineKeyboardButton("Для дела (Калькуляторы и ИИ-инструменты)", callback_data='menu_business')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("👋 Привет! Выберите раздел:", reply_markup=reply_markup)
    
    context.user_data['state'] = STATE_MAIN_MENU
    context.user_data['active_groq_mode'] = None
    return STATE_MAIN_MENU

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выводит главное меню после нажатия кнопки 'В главное меню'."""
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
    text_content = DEMO_SCENARIOS.get(demo_key, "⚠️ Описание демо-сценария не найдено. Проверьте ваш словарь DEMO_SCENARIOS.")
    
    # Определяем, к какому меню вернуться (постфикс не нужен, так как DEMO_SCENARIOS ключи не содержат _self/_business)
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
        f"Чтобы сменить режим, нажмите /start.", 
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
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(menu_self, pattern='^menu_self$'))
    application.add_handler(CallbackQueryHandler(menu_business, pattern='^menu_business$'))
    application.add_handler(CallbackQueryHandler(menu_calculator, pattern='^menu_calculator$'))
    application.add_handler(CallbackQueryHandler(ai_selection_handler, pattern='^ai_.*_self$|^ai_.*_business$'))
    application.add_handler(CallbackQueryHandler(show_demo_scenario, pattern='^demo_.*$'))
    application.add_handler(CallbackQueryHandler(activate_access, pattern='^activate_.*$'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))


async def run_webhook():
    """Асинхронный запуск Webhook-сервера."""
    if not application:
        return

    # Если мы запускаемся на Render (есть PORT и WEBHOOK_URL), то запускаем Webhook
    if os.environ.get('PORT') and WEBHOOK_URL:
        # Путь, по которому Telegram будет отправлять запросы (например, /selfdev-bot-webhook)
        webhook_path = "/"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
        
        # Установка Webhook для Telegram
        await application.bot.set_webhook(url=full_webhook_url)
        logger.info(f"✅ Webhook установлен: {full_webhook_url}")

        # Запуск встроенного Webhook-сервера python-telegram-bot
        # Обратите внимание: listen='0.0.0.0' и port=PORT - это критично для Render
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url
        )
        logger.info("🚀 Бот запущен в режиме Webhook на Render.")
    else:
        # Локальный запуск (Polling) или ошибка конфигурации
        logger.error("❌ Недостаточно переменных окружения (PORT или WEBHOOK_URL) для Webhook. Запуск невозможен.")


if __name__ == '__main__':
    # В этом блоке мы используем более чистый метод, чтобы избежать
    # конфликта event loop, вызывая run_webhook напрямую, если TELEGRAM_TOKEN есть.
    if TELEGRAM_TOKEN:
        try:
            # Пытаемся запустить Webhook в стандартном цикле asyncio
            asyncio.run(run_webhook())
        except RuntimeError as e:
            # Обработка случая, когда Render уже запустил loop (ошибка: RuntimeError: This event loop is already running)
            if "This event loop is already running" in str(e):
                logger.warning("Event loop уже запущен. Пробуем запустить run_webhook без asyncio.run()")
                # Добавляем задачу в уже существующий цикл
                asyncio.ensure_future(run_webhook())
                # Запускаем цикл в режиме ожидания (run_forever), чтобы процесс не завершился
                # Это необходимо для постоянной работы на Render
                asyncio.get_event_loop().run_forever()
            else:
                # Если ошибка другая, выбрасываем ее
                raise
