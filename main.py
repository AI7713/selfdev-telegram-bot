import os
import logging
import asyncio
import time
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import OrderedDict
from enum import Enum

# Импорты для AIOHTTP, HTTPX, и Reply Keyboard
import httpx
from aiohttp import web

# Импорты для Reply Keyboard и Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq, APIError
from telegram.constants import ParseMode

==============================================================================
0. КОНФИГУРАЦИЯ И ВЕРСИОНИРОВАНИЕ
==============================================================================
# ВЕРСИЯ БОТА - ОБНОВЛЯТЬ ПРИ КАЖДОМ ИЗМЕНЕНИИ!
BOT_VERSION = "v3.2.2"  # + SKILLTRAINER-Universal как пошаговый агент

"""
ИСТОРИЯ ВЕРСИЙ:
v1.0.0 - Первый бот (калькулятор маркетплейса)
v2.0.0 - Второй бот (AI инструменты + Groq)
v3.0.0 - Гибридный бот (объединение v1 + v2)
v3.1.0 - + Разбивка длинных ответов + Версионирование
v3.2.0 - + Growth фичи (прогресс-бар, виральность, A/B тесты)
v3.2.1 - + Исправления безопасности и производительности
v3.2.2 - + SKILLTRAINER-Universal (пошаговый агент)
"""

# Настройка логирования с версией
logging.basicConfig(
    format=f"%(asctime)s - %(name)s - {BOT_VERSION} - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение переменных окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

==============================================================================
1. НОВЫЕ КЛАССЫ ДЛЯ БЕЗОПАСНОСТИ И ПРОИЗВОДИТЕЛЬНОСТИ
==============================================================================
class LRUCache:
    """LRU кэш с ограничением размера для предотвращения утечек памяти"""
    def __init__(self, max_size: int = 1000):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key: Any) -> Optional[Any]:
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def set(self, key: Any, value: Any):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def __contains__(self, key: Any) -> bool:
        return key in self.cache

class RateLimiter:
    """Rate limiter для защиты от злоупотреблений"""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.requests = {}
        self.max_requests = max_requests
        self.window = window_seconds

    def is_allowed(self, user_id: int) -> bool:
        now = time.time()
        if user_id not in self.requests:
            self.requests[user_id] = []
        # Удаляем старые запросы
        user_requests = [req_time for req_time in self.requests[user_id] 
                        if now - req_time < self.window]
        if len(user_requests) < self.max_requests:
            user_requests.append(now)
            self.requests[user_id] = user_requests
            return True
        self.requests[user_id] = user_requests
        return False

class AIResponseCache:
    """Кэш для AI запросов для снижения нагрузки на API"""
    def __init__(self, max_size: int = 100):
        self.cache = LRUCache(max_size)

    def get_cache_key(self, prompt_key: str, user_query: str) -> str:
        """Создает ключ кэша на основе промта и запроса"""
        content = f"{prompt_key}:{user_query}"
        return hashlib.md5(content.encode()).hexdigest()

    def get_cached_response(self, prompt_key: str, user_query: str) -> Optional[str]:
        key = self.get_cache_key(prompt_key, user_query)
        return self.cache.get(key)

    def cache_response(self, prompt_key: str, user_query: str, response: str):
        key = self.get_cache_key(prompt_key, user_query)
        self.cache.set(key, response)

class BotState(Enum):
    """Enum для состояний бота вместо числовых констант"""
    MAIN_MENU = "main_menu"
    BUSINESS_MENU = "business_menu"
    AI_SELECTION = "ai_selection"
    CALCULATOR = "calculator"
    SKILLTRAINER = "skilltrainer"  # <-- НОВОЕ СОСТОЯНИЕ

==============================================================================
2. ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ
==============================================================================
# Инициализация Groq клиента
groq_client: Optional[Groq] = None
if GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized successfully")
    except Exception as e:
        logger.error(f"Ошибка инициализации Groq клиента: {e}")
else:
    logger.warning("GROQ_API_KEY не установлен. Функции AI будут недоступны.")

# Инициализация сервисов
user_stats_cache = LRUCache(max_size=500)
rate_limiter = RateLimiter(max_requests=15, window_seconds=60)
ai_cache = AIResponseCache(max_size=100)

==============================================================================
3. КОНСТАНТЫ И ПРОМТЫ
==============================================================================
# ВЕРСИЯ ПРОМТОВ И КОНФИГУРАЦИИ
CONFIG_VERSION = "v2.2"  # Обновлена

# КОНСТАНТЫ ДЛЯ КАЛЬКУЛЯТОРА ЭКОНОМИКИ (ИЗ ПЕРВОГО БОТА)
CALCULATOR_STEPS = [
    "💰 Себестоимость товара (руб):",
    "🏷️ Продажная цена (руб):",
    "📊 Комиссия маркетплейса (%):",
    "🚚 Логистика FBS (% от цены):",
    "📢 Бюджет на рекламу, ACOS (%):",
    "💸 Налог УСН (%):"
]

BENCHMARKS = {
    'наценка': {'низкая': 100, 'средняя': 200, 'высокая': 300},
    'комиссия_mp': {'низкая': 10, 'средняя': 15, 'высокая': 20},
    'логистика': {'низкая': 10, 'средняя': 15, 'высокая': 20},
    'acos': {'низкий': 5, 'средний': 10, 'высокий': 15},
    'чистая_маржа': {'низкая': 20, 'средняя': 30, 'высокая': 40}
}

# СИСТЕМНЫЕ ПРОМТЫ ДЛЯ AI
SYSTEM_PROMPTS: Dict[str, str] = {
    'grimoire': "Действуй как таинственный Гримуар...",
    'negotiator': "Ты — жесткий тренер по сложных переговорах...",
    'analyzer': "Вы — старший финансовый аналитик...",
    'coach': "Ты — энергичный, позитивный коуч...",
    'generator': "Ты — генератор прорывных бизнес-идей...",
    'editor': "Ты — профессиональный редактор...",
    'marketer': "Ты — эксперт по цифровому маркетингу...",
    'hr': "Ты — опытный HR-рекрутер...",
    'skilltrainer': (
        "Ты — **SKILLTRAINER-Universal**: через короткое интервью (5–7 вопросов) помогаешь пользователю понять, *что именно* тренировать; "
        "показываешь релевантные методики с превью-примерами; запускаешь сессию в одном из режимов **Sim / Drill / Build / Case / Quiz**. "
        "Работаешь по шагам с HUD и гейтами (DOD), даёшь короткие HINTS, соблюдаешь безопасность (PII/NDA). "
        "На финише формируешь **Finish Packet** и предлагаешь экспорт."
    )
}

# ДЕМО-СЦЕНАРИИ
DEMO_SCENARIOS: Dict[str, str] = {
    'grimoire': "🔮 Гримуар — это ваш мистический проводник...",
    'negotiator': "🗣️ Переговорщик — это ваш персональный спарринг-партнер...",
    'analyzer': "📈 Аналитик — ваш надежный помощник...",
    'coach': "🧘 Коуч поможет вам структурировать...",
    'generator': "💡 Генератор — это креативный хаб...",
    'editor': "📝 Редактор — ваш личный корректор...",
    'marketer': "🎯 Маркетолог — ваш наставник...",
    'hr': "🚀 HR-рекрутер помогает соискателям...",
    'skilltrainer': """
🎓 **SKILLTRAINER-Universal** — ваш персональный тренер навыков.

🔹 Проходит с вами короткое интервью (5 вопросов)  
🔹 Определяет, какой навык стоит прокачать  
🔹 Предлагает режим: Sim / Drill / Case / Quiz  
🔹 Запускает интерактивную сессию с подсказками  
🔹 Формирует **Finish Packet** с рекомендациями  

💡 Идеально для: переговоров, продаж, саморегуляции, публичных выступлений.
"""
}

# Вопросы интервью для SKILLTRAINER
SKILLTRAINER_QUESTIONS = [
    "1️⃣ Какая сфера вас интересует? (например: переговоры, продажи, саморегуляция)",
    "2️⃣ Какой у вас текущий уровень? (новичок / уверенный / эксперт)",
    "3️⃣ Какой результат вы хотите получить? (например: снизить цену аренды, уверенно выступать)",
    "4️⃣ Сколько времени готовы тратить на сессию? (5 / 10 / 15 минут)",
    "5️⃣ Есть ли у вас ограничения? (например: не хочу ролевые игры, только текст)"
]

==============================================================================
4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
==============================================================================
def sanitize_user_input(text: str, max_length: int = 2000) -> str:
    """Очищает пользовательский ввод от потенциально опасных символов"""
    if not text:
        return ""
    # Удаляем управляющие символы и ограничиваем длину
    cleaned = ''.join(char for char in text if char.isprintable() or char in '\n\r\t')
    return cleaned[:max_length]

def split_message_efficiently(text: str, max_length: int = 4096) -> List[str]:
    """Эффективно разбивает текст на части по границам предложений"""
    if len(text) <= max_length:
        return [text]
    # Пытаемся разбить по предложениям
    sentences = text.split('. ')
    parts = []
    current_part = ""
    for sentence in sentences:
        test_part = current_part + sentence + ". "
        if len(test_part) <= max_length:
            current_part = test_part
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = sentence + ". "
    if current_part:
        parts.append(current_part.strip())
    # Если все равно слишком длинные, разбиваем по жесткому ограничению
    final_parts = []
    for part in parts:
        if len(part) > max_length:
            # Разбиваем на равные части
            for i in range(0, len(part), max_length):
                final_parts.append(part[i:i+max_length])
        else:
            final_parts.append(part)
    return final_parts

def get_calculator_data_safe(context, index: int, default: float = 0.0) -> float:
    """Безопасное получение данных калькулятора с значением по умолчанию"""
    data = context.user_data.get('calculator_data', {})
    return data.get(index, default)

==============================================================================
5. GROWTH ФИЧИ - НОВЫЕ ФУНКЦИИ
==============================================================================
async def get_usage_stats(user_id: int) -> Dict[str, Any]:
    """Получает статистику использования для пользователя"""
    if user_id not in user_stats_cache:
        user_stats_cache.set(user_id, {
            'tools_used': 0,
            'ai_requests': 0,
            'calculator_uses': 0,
            'first_seen': datetime.now(),
            'last_active': datetime.now(),
            'ab_test_group': 'A' if user_id % 2 == 0 else 'B'  # A/B тестирование
        })
    stats = user_stats_cache.get(user_id)
    stats['last_active'] = datetime.now()
    user_stats_cache.set(user_id, stats)
    return stats

async def update_usage_stats(user_id: int, tool_type: str):
    """Обновляет статистику использования"""
    stats = await get_usage_stats(user_id)
    if tool_type == 'ai':
        stats['ai_requests'] += 1
        stats['tools_used'] = len(set([stats.get('last_tool', '')] + [tool_type]))
    elif tool_type == 'calculator':
        stats['calculator_uses'] += 1
        stats['tools_used'] = len(set([stats.get('last_tool', '')] + [tool_type]))
    stats['last_tool'] = tool_type
    user_stats_cache.set(user_id, stats)

async def show_usage_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прогресс использования бота"""
    user_id = update.message.from_user.id
    stats = await get_usage_stats(user_id)
    # Прогресс-бар инструментов
    tools_progress = "▰" * min(stats['tools_used'], 5) + "▱" * (5 - min(stats['tools_used'], 5))
    ai_progress = "▰" * min(stats['ai_requests'] // 3, 5) + "▱" * (5 - min(stats['ai_requests'] // 3, 5))
    progress_text = f"""
📊 ВАШ ПРОГРЕСС:
🛠️ Инструменты: {tools_progress} {stats['tools_used']}/5
🤖 AI запросы: {ai_progress} {stats['ai_requests']}+
📈 Калькулятор: {stats['calculator_uses']} использований
🎯 Группа теста: {stats['ab_test_group']}
💡 Исследуйте больше инструментов для увеличения прогресса!
"""
    await update.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)

async def show_referral_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает реферальную программу"""
    user_id = update.message.from_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    referral_text = f"""
🎁 ПРИГЛАСИ ДРУЗЕЙ - ПОЛУЧИ БОНУСЫ!
Пригласи друга по ссылке:
{ref_link}
За каждого друга:
✅ +5 дополнительных AI запросов
✅ Расширенная статистика
✅ Специальные возможности
💬 Просто отправь другу эту ссылку!
"""
    await update.message.reply_text(referral_text, parse_mode=ParseMode.MARKDOWN)

async def get_personal_recommendation(user_id: int) -> str:
    """Генерирует персональные рекомендации на основе статистики"""
    stats = await get_usage_stats(user_id)
    if stats['calculator_uses'] > stats['ai_requests']:
        return "🎯 **Вам подойдет:** Аналитик + Маркетолог (для углубления анализа)"
    elif stats['ai_requests'] > 5:
        return "🎯 **Попробуйте:** Калькулятор для точных финансовых расчетов"
    else:
        return "🎯 **Начните с:** Быстрый старт в меню 'Для себя'"

==============================================================================
6. ФУНКЦИИ КАЛЬКУЛЯТОРА ЭКОНОМИКИ
==============================================================================
def calculate_economy_metrics(data):
    """Расчет всех финансовых метрик"""
    себестоимость = data[0]
    цена = data[1]
    комиссия_процент = data[2]
    логистика_процент = data[3]
    acos_процент = data[4]
    налог_процент = data[5]
    выручка = цена
    комиссия = выручка * комиссия_процент / 100
    логистика = выручка * логистика_процент / 100
    cm1 = выручка - себестоимость - комиссия - логистика
    реклама = выручка * acos_процент / 100
    cm2 = cm1 - реклама
    налог = выручка * налог_процент / 100
    чистая_прибыль = cm2 - налог
    наценка_процент = ((цена - себестоимость) / себестоимость) * 100 if себестоимость > 0 else 0
    маржа_cm1_процент = (cm1 / выручка) * 100 if выручка > 0 else 0
    маржа_cm2_процент = (cm2 / выручка) * 100 if выручка > 0 else 0
    чистая_маржа_процент = (чистая_прибыль / выручка) * 100 if выручка > 0 else 0
    return {
        'выручка': выручка,
        'себестоимость': себестоимость,
        'комиссия': комиссия,
        'комиссия_%': комиссия_процент,
        'логистика': логистика,
        'логистика_%': логистика_процент,
        'cm1': cm1,
        'маржа_cm1_%': маржа_cm1_процент,
        'реклама': реклама,
        'acos_%': acos_процент,
        'cm2': cm2,
        'маржа_cm2_%': маржа_cm2_процент,
        'налог': налог,
        'налог_%': налог_процент,
        'чистая_прибыль': чистая_прибыль,
        'чистая_маржа_%': чистая_маржа_процент,
        'наценка_%': наценка_процент
    }

def generate_recommendations(metrics):
    """Генерация рекомендаций на основе метрик"""
    recommendations = []
    if metrics['наценка_%'] > BENCHMARKS['наценка']['высокая']:
        recommendations.append("🚀 Отличная наценка! Товар имеет высокий потенциал прибыли")
    elif metrics['наценка_%'] < BENCHMARKS['наценка']['низкая']:
        recommendations.append("📈 Низкая наценка. Рассмотрите повышение цены или поиск поставщика с лучшими условиями")
    if metrics['комиссия_%'] > BENCHMARKS['комиссия_mp']['высокая']:
        recommendations.append("📊 Комиссия выше среднего. Рассмотрите маркетплейсы с меньшей комиссией")
    elif metrics['комиссия_%'] < BENCHMARKS['комиссия_mp']['низкая']:
        recommendations.append("💰 Низкая комиссия - хорошие условия!")
    if metrics['логистика_%'] > BENCHMARKS['логистика']['высокая']:
        recommendations.append("🚚 Логистика дороговата. Ищите способы оптимизации доставки или упаковки")
    elif metrics['логистика_%'] < BENCHMARKS['логистика']['низкая']:
        recommendations.append("📦 Логистика эффективна!")
    if metrics['acos_%'] > BENCHMARKS['acos']['высокий']:
        recommendations.append("📢 Высокий ACOS. Оптимизируйте рекламные кампании или когорты")
    elif metrics['acos_%'] < BENCHMARKS['acos']['низкий']:
        recommendations.append("🎯 Эффективная реклама!")
    if metrics['чистая_маржа_%'] > BENCHMARKS['чистая_маржа']['высокая']:
        recommendations.append("✅ Отличная рентабельность! Товар готов к масштабированию")
    elif metrics['чистая_маржа_%'] < BENCHMARKS['чистая_маржа']['низкая']:
        recommendations.append("💸 Низкая рентабельность. Рассмотрите повышение цены или снижение закупочной стоимости")
    return recommendations if recommendations else ["📊 Показатели в норме. Продолжайте в том же духе!"]

async def calculate_and_show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расчет и показ результатов калькулятора"""
    data = [get_calculator_data_safe(context, i) for i in range(6)]
    metrics = calculate_economy_metrics(data)
    recommendations = generate_recommendations(metrics)
    report = f"""📊 **ФИНАНСОВЫЙ АНАЛИЗ ТОВАРА**
💰 ВЫРУЧКА И ЗАТРАТЫ:
• Выручка: {metrics['выручка']:.1f} ₽
• Себестоимость: {metrics['себестоимость']:.1f} ₽
• Комиссия MP: {metrics['комиссия']:.1f} ₽ ({metrics['комиссия_%']:.1f}%)
• Логистика FBS: {metrics['логистика']:.1f} ₽ ({metrics['логистика_%']:.1f}%)
• Реклама (ACOS): {metrics['реклама']:.1f} ₽ ({metrics['acos_%']:.1f}%)
• Налог УСН: {metrics['налог']:.1f} ₽ ({metrics['налог_%']:.1f}%)
🎯 УРОВНИ ПРИБЫЛИ:
• CM1 (до рекламы): {metrics['cm1']:.1f} ₽ ({metrics['маржа_cm1_%']:.1f}%)
• CM2 (после рекламы): {metrics['cm2']:.1f} ₽ ({metrics['маржа_cm2_%']:.1f}%)
• Чистая прибыль: {metrics['чистая_прибыль']:.1f} ₽ ({metrics['чистая_маржа_%']:.1f}%)
📈 КЛЮЧЕВЫЕ МЕТРИКИ:
• Наценка: {metrics['наценка_%']:.1f}% {'🚀' if metrics['наценка_%'] > 300 else '✅' if metrics['наценка_%'] > 200 else '📊'}
• Рентабельность: {metrics['чистая_маржа_%']:.1f}% {'✅' if metrics['чистая_маржа_%'] > 30 else '📊'}
💡 РЕКОМЕНДАЦИИ:
"""
    for rec in recommendations:
        report += f"• {rec}\n"
    keyboard = [
        [KeyboardButton("🔄 Новый расчет")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(report, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    await update_usage_stats(update.message.from_user.id, 'calculator')

async def start_economy_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начало калькулятора экономики"""
    context.user_data['calculator_step'] = 0
    context.user_data['calculator_data'] = {}
    # УНИВЕРСАЛЬНЫЙ ПОДХОД для любого типа update
    if update.callback_query:
        # Для callback query
        await update.callback_query.message.reply_text(
            "🛍️ **РАСЧЕТ ЭКОНОМИКИ МАРКЕТПЛЕЙСА**\n\n"
            "Введите данные вашего товара:\n\n"
            + CALCULATOR_STEPS[0],
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Для обычного сообщения
        await update.message.reply_text(
            "🛍️ **РАСЧЕТ ЭКОНОМИКИ МАРКЕТПЛЕЙСА**\n\n"
            "Введите данные вашего товара:\n\n"
            + CALCULATOR_STEPS[0],
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_economy_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик калькулятора с защитой от ошибок"""
    user = update.message.from_user
    text = update.message.text
    step = context.user_data.get('calculator_step', 0)
    if text == "🔙 Назад":
        if step == 0:
            context.user_data['state'] = BotState.BUSINESS_MENU
            await show_business_menu_from_callback(update, context)
        else:
            context.user_data['calculator_step'] = step - 1
            await update.message.reply_text(CALCULATOR_STEPS[step - 1])
        return
    if text == "🔄 Новый расчет":
        context.user_data['calculator_step'] = 0
        context.user_data['calculator_data'] = {}
        await start_economy_calculator(update, context)
        return
    try:
        value = float(text)
        if value < 0:
            await update.message.reply_text("❌ Число должно быть положительным. Попробуйте еще раз:")
            return
        context.user_data['calculator_data'][step] = value
        context.user_data['calculator_step'] = step + 1
        if step + 1 < len(CALCULATOR_STEPS):
            await update.message.reply_text(CALCULATOR_STEPS[step + 1])
        else:
            await calculate_and_show_results(update, context)
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите число:")

==============================================================================
7. SKILLTRAINER-UNIVERSAL – ПОШАГОВЫЙ АГЕНТ
==============================================================================
async def _ask_skilltrainer_question(update: Update, context: ContextTypes.DEFAULT_TYPE, step: int):
    if step < len(SKILLTRAINER_QUESTIONS):
        await update.message.reply_text(SKILLTRAINER_QUESTIONS[step])
    context.user_data['skilltrainer_step'] = step

async def _generate_skilltrainer_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    answers = user_data.get('skilltrainer_data', {})
    mode = user_data.get('skilltrainer_mode', 'Drill')

    context_summary = f"""
Сфера: {answers.get(0, 'не указана')}
Уровень: {answers.get(1, 'не указан')}
Цель: {answers.get(2, 'не указана')}
Время: {answers.get(3, 'не указано')}
Ограничения: {answers.get(4, 'нет')}
Режим: {mode}
"""

    system_prompt = f"""Ты — SKILLTRAINER-Universal. Создай персонализированную обучающую сессию в режиме {mode}, основанную на данных пользователя. Соблюдай:
- Нейтральный тон
- Безопасность (не запрашивай PII, не используй гипотетические данные)
- Короткие HINTS (≤200 символов)
- Чёткую структуру: цель → шаги → задание → обратная связь
- На финише — Finish Packet: краткое резюме, рекомендации, экспорт (текстом)
"""

    user_prompt = f"Запусти сессию в режиме {mode} для следующего пользователя:\n{context_summary}"

    if not groq_client:
        await update.message.reply_text("❌ AI недоступен. Проверьте настройки.")
        context.user_data['state'] = BotState.MAIN_MENU
        return

    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.1-70b-versatile",
            max_tokens=3000
        )
        response = chat_completion.choices[0].message.content

        await send_long_message(
            update.message.chat.id,
            response,
            context,
            prefix="🎓 **Ваша сессия SKILLTRAINER**:\n\n",
            parse_mode=None  # Безопасно!
        )

        await update_usage_stats(update.message.from_user.id, 'ai')
        context.user_data['state'] = BotState.MAIN_MENU

    except Exception as e:
        logger.error(f"Ошибка генерации SKILLTRAINER: {e}")
        await update.message.reply_text("❌ Не удалось сгенерировать сессию. Попробуйте позже.")
        context.user_data['state'] = BotState.MAIN_MENU

async def handle_skilltrainer_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    step = user_data.get('skilltrainer_step', 0)
    answers = user_data.get('skilltrainer_data', {})

    # Сохраняем ответ
    answers[step] = sanitize_user_input(update.message.text)[:300]
    user_data['skilltrainer_data'] = answers

    if step < 4:
        await _ask_skilltrainer_question(update, context, step + 1)
    elif step == 4:
        keyboard = [
            [KeyboardButton("🎭 Sim (сценарий)"), KeyboardButton("🔁 Drill (отработка)")],
            [KeyboardButton("🧩 Case (кейс)"), KeyboardButton("🧠 Quiz (тест)")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "✅ Интервью завершено!\n\nВыберите режим тренировки:",
            reply_markup=reply_markup
        )
        user_data['skilltrainer_step'] = 5
    elif step == 5:
        mode_map = {
            "🎭 Sim (сценарий)": "Sim",
            "🔁 Drill (отработка)": "Drill",
            "🧩 Case (кейс)": "Case",
            "🧠 Quiz (тест)": "Quiz"
        }
        mode_text = update.message.text
        if mode_text in mode_map:
            user_data['skilltrainer_mode'] = mode_map[mode_text]
            await update.message.reply_text("⏳ Формирую вашу сессию...")
            await _generate_skilltrainer_session(update, context)
        else:
            await update.message.reply_text("Пожалуйста, выберите режим из кнопок.")

==============================================================================
8. ФУНКЦИИ ГЕНЕРАЦИИ ТЕКСТА ЧЕРЕЗ GROQ С РАЗБИВКОЙ ОТВЕТОВ
==============================================================================
async def send_long_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE,
                            prefix: str = "", parse_mode: str = ParseMode.MARKDOWN):
    """Разбивает длинные сообщения на части для Telegram"""
    parts = split_message_efficiently(text)
    total_parts = len(parts)
    for i, part in enumerate(parts, 1):
        part_prefix = prefix if total_parts == 1 else f"{prefix}*({i}/{total_parts})*\n"
        await context.bot.send_message(chat_id, f"{part_prefix}{part}", parse_mode=parse_mode)

async def handle_groq_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt_key: str):
    """Отправляет запрос в Groq с разбивкой ответов и rate limiting"""
    if not groq_client or not update.message:
        return
    user_id = update.message.from_user.id
    # Проверка rate limiting
    if not rate_limiter.is_allowed(user_id):
        await update.message.reply_text("🚫 Слишком много запросов. Подождите минуту.")
        return
    user_query = sanitize_user_input(update.message.text)
    system_prompt = SYSTEM_PROMPTS.get(prompt_key, "Вы — полезный ассистент.")
    await update.message.chat.send_message(f"⌛ **{prompt_key.capitalize()}** обрабатывает ваш запрос...", parse_mode=ParseMode.MARKDOWN)
    try:
        # Проверка кэша
        cached_response = ai_cache.get_cached_response(prompt_key, user_query)
        if cached_response:
            await send_long_message(
                update.message.chat.id,
                cached_response,
                context,
                prefix=f"🤖 Ответ {prompt_key.capitalize()} (из кэша):\n\n",
                parse_mode=None  # Безопасно!
            )
            await update_usage_stats(user_id, 'ai')
            return
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]
        chat_completion = groq_client.chat.completions.create(
            messages=messages,
            model="llama-3.1-8b-instant",
            max_tokens=4000
        )
        ai_response = chat_completion.choices[0].message.content
        # Сохраняем в кэш
        ai_cache.cache_response(prompt_key, user_query, ai_response)
        await send_long_message(
            update.message.chat.id,
            ai_response,
            context,
            prefix=f"🤖 Ответ {prompt_key.capitalize()}:\n\n",
            parse_mode=None  # Безопасно!
        )
        await update_usage_stats(user_id, 'ai')
    except APIError as e:
        logger.error(f"ОШИБКА GROQ API: {e}")
        if e.status_code == 429:
            user_message = "❌ **Превышен лимит запросов.** Подождите минуту."
        elif e.status_code == 400:
            user_message = "❌ **Ошибка 400: Неверный запрос или лимиты.**"
        elif e.status_code == 401:
            user_message = "❌ **Ошибка 401: Неверный API ключ.**"
        else:
            user_message = f"❌ **Ошибка Groq API:** Код {e.status_code}"
        await update.message.chat.send_message(user_message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")
        await update.message.chat.send_message("Произошла ошибка при обращении к AI.", parse_mode=ParseMode.MARKDOWN)

==============================================================================
9. ОСНОВНЫЕ ФУНКЦИИ БОТА
==============================================================================
# Создание постоянной клавиатуры
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("/start"), KeyboardButton("/menu"), KeyboardButton("/progress")]],
    one_time_keyboard=False,
    resize_keyboard=True
)

--- Общие Хендлеры и Меню ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Обрабатывает команду /start с A/B тестированием"""
    if not update.message:
        return BotState.MAIN_MENU
    user_id = update.message.from_user.id
    stats = await get_usage_stats(user_id)
    # A/B ТЕСТИРОВАНИЕ ИНТЕРФЕЙСОВ
    if stats['ab_test_group'] == 'A':
        # Группа A - стандартный интерфейс
        inline_keyboard = [
            [InlineKeyboardButton("Для себя (ИИ-инструменты)", callback_data='menu_self')],
            [InlineKeyboardButton("Для дела (Калькуляторы и ИИ-инструменты)", callback_data='menu_business')]
        ]
        welcome_text = "👋 Привет! Выберите инструмент:"
    else:
        # Группа B - улучшенный интерфейс
        inline_keyboard = [
            [InlineKeyboardButton("🧠 Личный рост", callback_data='menu_self')],
            [InlineKeyboardButton("🚀 Бизнес и карьера", callback_data='menu_business')],
            [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')]
        ]
        welcome_text = f"🎯 Добро пожаловать! Ваша группа: {stats['ab_test_group']}\nВыберите направление:"
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    await update.message.reply_text("👋 Привет! Используйте нижнюю панель для навигации.", reply_markup=REPLY_KEYBOARD)
    # Показываем прогресс для активных пользователей
    if stats['tools_used'] > 0:
        await show_usage_progress(update, context)
    await update.message.reply_text(welcome_text, reply_markup=inline_markup)
    context.user_data['state'] = BotState.MAIN_MENU
    context.user_data['active_groq_mode'] = None
    # Логируем запуск с версией
    logger.info(f"{BOT_VERSION} - User {user_id} started bot (Group: {stats['ab_test_group']})")
    return BotState.MAIN_MENU

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Обрабатывает команду /menu"""
    return await start(update, context)

async def version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущую версию бота"""
    version_info = f"""
🤖 Personal Growth AI {BOT_VERSION}
📊 КОМПОНЕНТЫ:
• Архитектура: {BOT_VERSION} (Гибридный бот + Growth + Безопасность)
• Конфигурация: {CONFIG_VERSION}
• Калькулятор: v1.0 (полный из первого бота)
• AI движок: v2.0 (Groq + 8 инструментов + кэширование)
🔄 ЧТО ВКЛЮЧЕНО:
✅ Детальный калькулятор маркетплейса (6 шагов)
✅ 8 AI-инструментов с системными промтами
✅ SKILLTRAINER-Universal (пошаговый агент)
✅ Разбивка длинных ответов (>4096 символов)
✅ Growth фичи (A/B тесты, прогресс-бар, виральность)
✅ Inline + Reply навигация
✅ Webhook для Render
✅ Rate limiting и кэширование
✅ Защита от инъекций
💡 Используйте /progress для вашей статистики
"""
    await update.message.reply_text(version_info, parse_mode=ParseMode.MARKDOWN)

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прогресс использования"""
    await show_usage_progress(update, context)
    # Добавляем персональные рекомендации
    user_id = update.message.from_user.id
    recommendation = await get_personal_recommendation(user_id)
    await update.message.reply_text(recommendation, parse_mode=ParseMode.MARKDOWN)

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает реферальную программу"""
    await show_referral_program(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Выводит главное меню"""
    query = update.callback_query
    if query:
        await query.answer()
    user_id = query.from_user.id
    stats = await get_usage_stats(user_id)
    if stats['ab_test_group'] == 'A':
        keyboard = [
            [InlineKeyboardButton("Для себя (ИИ-инструменты)", callback_data='menu_self')],
            [InlineKeyboardButton("Для дела (Калькуляторы и ИИ-инструменты)", callback_data='menu_business')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🧠 Личный рост", callback_data='menu_self')],
            [InlineKeyboardButton("🚀 Бизнес и карьера", callback_data='menu_business')],
            [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')]
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("👋 Выберите раздел:", reply_markup=reply_markup)
    context.user_data['state'] = BotState.MAIN_MENU
    context.user_data['active_groq_mode'] = None
    return BotState.MAIN_MENU

--- Меню "Для себя" ---
async def menu_self(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Обрабатывает выбор 'Для себя'"""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🔮 Гримуар", callback_data='ai_grimoire_self'), 
         InlineKeyboardButton("📈 Аналитик", callback_data='ai_analyzer_self')],
        [InlineKeyboardButton("🧘 Коуч", callback_data='ai_coach_self'), 
         InlineKeyboardButton("💡 Генератор", callback_data='ai_generator_self')],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Вы выбрали *Для себя*. Выберите ИИ-инструмент:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    context.user_data['state'] = BotState.AI_SELECTION
    context.user_data['active_groq_mode'] = None
    return BotState.AI_SELECTION

--- Меню "Для дела" ---
async def menu_business(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Обрабатывает выбор 'Для дела'"""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📊 Калькулятор маркетплейсов", callback_data='menu_calculator')],
        [InlineKeyboardButton("🗣️ Переговорщик", callback_data='ai_negotiator_business'), 
         InlineKeyboardButton("🎓 SKILLTRAINER", callback_data='ai_skilltrainer_business')],
        [InlineKeyboardButton("📝 Редактор", callback_data='ai_editor_business'), 
         InlineKeyboardButton("🎯 Маркетолог", callback_data='ai_marketer_business')],
        [InlineKeyboardButton("🚀 HR-рекрутер", callback_data='ai_hr_business')],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Вы выбрали *Для дела*. Выберите инструмент:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    context.user_data['state'] = BotState.BUSINESS_MENU
    context.user_data['active_groq_mode'] = None
    return BotState.BUSINESS_MENU

async def show_business_menu_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню бизнес-инструментов"""
    keyboard = [
        [InlineKeyboardButton("📊 Калькулятор маркетплейсов", callback_data='menu_calculator')],
        [InlineKeyboardButton("🗣️ Переговорщик", callback_data='ai_negotiator_business'),
         InlineKeyboardButton("🎓 SKILLTRAINER", callback_data='ai_skilltrainer_business')],
        [InlineKeyboardButton("📝 Редактор", callback_data='ai_editor_business'),
         InlineKeyboardButton("🎯 Маркетолог", callback_data='ai_marketer_business')],
        [InlineKeyboardButton("🚀 HR-рекрутер", callback_data='ai_hr_business')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🚀 **ДЛЯ ДЕЛА**\n\nИнструменты для профессионального роста и бизнеса:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🚀 **ДЛЯ ДЕЛА**\n\nИнструменты для профессионального роста и бизнеса:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

--- Обработка выбора AI ---
def get_ai_keyboard(prompt_key: str, back_button: str) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для выбранного AI"""
    keyboard = [
        [InlineKeyboardButton("💡 Демо-сценарий (что он умеет?)", callback_data=f'demo_{prompt_key}')],
        [InlineKeyboardButton("✅ Активировать платный доступ (10 кнопок)", callback_data=f'activate_{prompt_key}')],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')],
        [InlineKeyboardButton("🔙 Назад", callback_data=back_button)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def ai_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Обрабатывает выбор конкретного AI"""
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    prompt_key = callback_data.split('_', 1)[1]  # <- исправлено для skilltrainer
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
    context.user_data['state'] = BotState.AI_SELECTION
    context.user_data['active_groq_mode'] = None
    return BotState.AI_SELECTION

async def show_demo_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Выводит демо-сценарий для выбранного AI"""
    query = update.callback_query
    await query.answer()
    demo_key = query.data.split('_', 1)[1]  # <- исправлено
    text_content = DEMO_SCENARIOS.get(demo_key, "⚠️ Описание демо-сценария не найдено.")
    back_to_menu_key = 'menu_self' 
    if context.user_data.get('state') == BotState.BUSINESS_MENU:
        back_to_menu_key = 'menu_business'
    keyboard = [[InlineKeyboardButton("🔙 Назад к выбору AI", callback_data=back_to_menu_key)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text_content, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    context.user_data['state'] = BotState.AI_SELECTION if back_to_menu_key == 'menu_self' else BotState.BUSINESS_MENU
    return context.user_data['state']

async def activate_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Активирует платный доступ"""
    query = update.callback_query
    await query.answer()
    prompt_key = query.data.split('_', 1)[1]  # <- исправлено
    context.user_data['active_groq_mode'] = prompt_key
    await query.edit_message_text(
        f"✅ Режим **{prompt_key.capitalize()}** активирован!\n\n"
        f"Напишите ваш первый запрос, и {prompt_key.capitalize()} приступит к работе.\n\n"
        f"Чтобы сменить режим, используйте команду /menu.", 
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['state'] = BotState.AI_SELECTION
    return context.user_data['state']

async def show_progress_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Обрабатывает показ прогресса из inline кнопки"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    stats = await get_usage_stats(user_id)
    # Прогресс-бар инструментов
    tools_progress = "▰" * min(stats['tools_used'], 5) + "▱" * (5 - min(stats['tools_used'], 5))
    ai_progress = "▰" * min(stats['ai_requests'] // 3, 5) + "▱" * (5 - min(stats['ai_requests'] // 3, 5))
    progress_text = f"""
📊 ВАШ ПРОГРЕСС:
🛠️ Инструменты: {tools_progress} {stats['tools_used']}/5
🤖 AI запросы: {ai_progress} {stats['ai_requests']}+
📈 Калькулятор: {stats['calculator_uses']} использований
🎯 Группа теста: {stats['ab_test_group']}
💡 Исследуйте больше инструментов для увеличения прогресса!
"""
    # Отправляем прогресс
    await query.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)
    # Добавляем персональные рекомендации
    recommendation = await get_personal_recommendation(user_id)
    await query.message.reply_text(recommendation, parse_mode=ParseMode.MARKDOWN)
    return context.user_data.get('state', BotState.MAIN_MENU)

--- Калькулятор Маркетплейсов (STATE_CALCULATOR) ---
async def menu_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Запускает режим калькулятора"""
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = BotState.CALCULATOR
    context.user_data['active_groq_mode'] = None
    await start_economy_calculator(update, context)
    return BotState.CALCULATOR

--- Обработка всех остальных текстовых сообщений ---
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Единый хендлер для всех текстовых сообщений с growth фичами"""
    user_text = update.message.text
    user_id = update.message.from_user.id

    # ВИРАЛЬНЫЕ МЕХАНИКИ - обработка реферальных запросов
    if any(word in user_text.lower() for word in ['пригласи', 'друг', 'реферал', 'ссылка']):
        await show_referral_program(update, context)
        return BotState.MAIN_MENU

    # Обработка прогресса
    if any(word in user_text.lower() for word in ['прогресс', 'статистика', 'стата']):
        await show_usage_progress(update, context)
        return BotState.MAIN_MENU

    current_state = context.user_data.get('state', BotState.MAIN_MENU)

    if current_state == BotState.CALCULATOR:
        return await handle_economy_calculator(update, context)

    elif current_state == BotState.SKILLTRAINER:
        return await handle_skilltrainer_session(update, context)

    elif context.user_data.get('active_groq_mode'):
        active_mode = context.user_data['active_groq_mode']

        # Особый случай: SKILLTRAINER — запуск интервью
        if active_mode == 'skilltrainer':
            context.user_data['state'] = BotState.SKILLTRAINER
            context.user_data['skilltrainer_step'] = 0
            context.user_data['skilltrainer_data'] = {}
            await update.message.reply_text(
                "🎓 **SKILLTRAINER-Universal** запущен!\n\n"
                "Я помогу вам определить, какой навык стоит тренировать.\n\n"
                "👉 Ответьте на 5 коротких вопросов.",
                parse_mode=ParseMode.MARKDOWN
            )
            await _ask_skilltrainer_question(update, context, 0)
            return BotState.SKILLTRAINER

        # Обычные AI-инструменты
        elif active_mode in SYSTEM_PROMPTS:
            return await handle_groq_request(update, context, active_mode)
        else:
            await update.message.reply_text("❓ Неизвестный AI режим. Нажмите /start для сброса.")
            return BotState.MAIN_MENU

    elif current_state in (BotState.AI_SELECTION, BotState.BUSINESS_MENU):
        await update.message.reply_text("❓ Вы отправили текст, но не активировали ни один из ИИ-инструментов. Нажмите на кнопку 'Активировать' под нужным инструментом, чтобы начать диалог, или /start для возврата в главное меню.")
        return current_state

    else:
        # Показываем помощь с growth фичами
        help_text = f"""
🤖 Personal Growth AI {BOT_VERSION}
💡 Доступные команды:
/start - Главное меню
/version - Информация о версии
/progress - Ваш прогресс и статистика
/referral - Пригласить друзей
/menu - Альтернативное меню
🎯 Быстрый старт:
• Напишите "пригласи друга" для реферальной программы
• Используйте "мой прогресс" для статистики
• Выберите инструмент из меню
🚀 Исследуйте разные инструменты для увеличения прогресса!
"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        return current_state

==============================================================================
10. НАСТРОЙКА И ЗАПУСК БОТА (WEBHOOK/RENDER)
==============================================================================
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN не установлен. Запуск невозможен.")
    application = None
else:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Подключение хендлеров с growth фичами
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("version", version_command))
    application.add_handler(CommandHandler("progress", progress_command))
    application.add_handler(CommandHandler("referral", referral_command))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(menu_self, pattern='^menu_self$'))
    application.add_handler(CallbackQueryHandler(menu_business, pattern='^menu_business$'))
    application.add_handler(CallbackQueryHandler(menu_calculator, pattern='^menu_calculator$'))
    application.add_handler(CallbackQueryHandler(ai_selection_handler, pattern=r'^ai_.+_(self|business)$'))
    application.add_handler(CallbackQueryHandler(show_demo_scenario, pattern=r'^demo_.+$'))
    application.add_handler(CallbackQueryHandler(activate_access, pattern=r'^activate_.+$'))
    application.add_handler(CallbackQueryHandler(show_progress_handler, pattern='^show_progress$'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

--- AIOHTTP HANDLER ---
async def telegram_webhook_handler(request: web.Request) -> web.Response:
    """Обрабатывает входящие запросы от Telegram"""
    global application
    if application is None:
        return web.Response(status=500, text="Application not initialized.")
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return web.Response(text="OK")

async def init_webhook_and_start_server(application: Application):
    """Устанавливает webhook и запускает AIOHTTP сервер"""
    if not os.environ.get('PORT') or not WEBHOOK_URL:
        logger.error("❌ Недостаточно переменных окружения (PORT или WEBHOOK_URL) для Webhook.")
        return
    webhook_path = "/"
    full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
            json={"url": full_webhook_url}
        )
        if response.status_code == 200 and response.json().get('ok'):
            logger.info(f"{BOT_VERSION} - ✅ Webhook успешно установлен: {full_webhook_url}")
        else:
            logger.error(f"{BOT_VERSION} - ❌ Ошибка установки Webhook: {response.text}")
            return
    app = web.Application()
    app.add_routes([web.post(webhook_path, telegram_webhook_handler)])
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    site = web.TCPSite(app_runner, '0.0.0.0', PORT)
    logger.info(f"{BOT_VERSION} - 🚀 AIOHTTP Server запущен на порту {PORT}")
    await application.initialize()
    await site.start()
    await asyncio.Future() 

if __name__ == '__main__':
    if TELEGRAM_TOKEN and os.environ.get('PORT') and application:
        try:
            logger.info(f"{BOT_VERSION} - Starting bot with security and performance improvements...")
            asyncio.run(init_webhook_and_start_server(application))
        except KeyboardInterrupt:
            logger.info(f"{BOT_VERSION} - Бот остановлен вручную.")
        except Exception as e:
            logger.error(f"{BOT_VERSION} - Критическая ошибка при запуске бота: {e}")
