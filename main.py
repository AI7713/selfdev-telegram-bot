import os
import logging
import asyncio
import time
import hashlib
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from collections import OrderedDict
from enum import Enum
import httpx
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq, APIError
from telegram.constants import ParseMode

# ==============================================================================
# 0. КОНФИГУРАЦИЯ И ВЕРСИОНИРОВАНИЕ
# ==============================================================================
BOT_VERSION = "v3.3.5"  # Финальная версия: UX + исправления кнопок

logging.basicConfig(
    format=f"%(asctime)s - %(name)s - {BOT_VERSION} - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 10000))  # Render default
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# ==============================================================================
# 1. КЛАССЫ
# ==============================================================================
class LRUCache:
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
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.requests = {}
        self.max_requests = max_requests
        self.window = window_seconds
    def is_allowed(self, user_id: int) -> bool:
        now = time.time()
        if user_id not in self.requests:
            self.requests[user_id] = []
        user_requests = [req_time for req_time in self.requests[user_id] 
                        if now - req_time < self.window]
        if len(user_requests) < self.max_requests:
            user_requests.append(now)
            self.requests[user_id] = user_requests
            return True
        self.requests[user_id] = user_requests
        return False

class AIResponseCache:
    def __init__(self, max_size: int = 100):
        self.cache = LRUCache(max_size)
    def get_cache_key(self, prompt_key: str, user_query: str) -> str:
        content = f"{prompt_key}:{user_query}"
        return hashlib.md5(content.encode()).hexdigest()
    def get_cached_response(self, prompt_key: str, user_query: str) -> Optional[str]:
        key = self.get_cache_key(prompt_key, user_query)
        return self.cache.get(key)
    def cache_response(self, prompt_key: str, user_query: str, response: str):
        key = self.get_cache_key(prompt_key, user_query)
        self.cache.set(key, response)

class BotState(Enum):
    MAIN_MENU = "main_menu"
    BUSINESS_MENU = "business_menu"
    AI_SELECTION = "ai_selection"
    CALCULATOR = "calculator"

class SessionState(Enum):
    INTERVIEW = "interview"
    MODE_SELECTION = "mode_select"
    TRAINING = "training"
    GATE_CHECK = "gate_check"
    FINISH = "finish"

class TrainingMode(Enum):
    SIM = "sim"
    DRILL = "drill"
    BUILD = "build"
    CASE = "case"
    QUIZ = "quiz"

class SkillSession:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.state: SessionState = SessionState.INTERVIEW
        self.current_step: int = 0
        self.max_steps: int = 8
        self.answers: Dict[int, str] = {}
        self.selected_mode: Optional[TrainingMode] = None
        self.gates_passed: Set[str] = set()
        self.last_hint: Optional[str] = None
        self.created_at: datetime = datetime.now()
        self.progress: float = 0.0
        self.finish_packet: Optional[str] = None
        self.training_complete: bool = False
    def update_progress(self):
        self.progress = min(1.0, (self.current_step + 1) / self.max_steps)
    def add_answer(self, step: int, answer: str):
        self.answers[step] = answer
        self.current_step = step + 1
        self.update_progress()
    def pass_gate(self, gate_id: str):
        self.gates_passed.add(gate_id)
    def set_hint(self, hint: str):
        if len(hint) <= 240:
            self.last_hint = hint
    def is_gate_passed(self, gate_id: str) -> bool:
        return gate_id in self.gates_passed

# ==============================================================================
# 2. ИНИЦИАЛИЗАЦИЯ
# ==============================================================================
groq_client: Optional[Groq] = None
if GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized successfully")
    except Exception as e:
        logger.error(f"Ошибка инициализации Groq клиента: {type(e).__name__}")
else:
    logger.warning("GROQ_API_KEY не установлен. Функции AI будут недоступны.")

user_stats_cache = LRUCache(max_size=500)
rate_limiter = RateLimiter(max_requests=15, window_seconds=60)
ai_cache = AIResponseCache(max_size=100)
active_skill_sessions: Dict[int, SkillSession] = {}

# ==============================================================================
# 3. КОНСТАНТЫ
# ==============================================================================
CONFIG_VERSION = "v3.0"
SKILLTRAINER_VERSION = "v1.0"

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

SYSTEM_PROMPTS: Dict[str, str] = {
    'grimoire': "Действуй как таинственный Гримуар...",
    'negotiator': "Ты — тренер навыков. Задавай 5-7 вопросов для диагностики. Предлагай методики тренировок. Проводи сессии в разных режимах. Используй только обычный текст без форматирования.",
    'analyzer': "Вы — старший финансовый анализик...",
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

DEMO_SCENARIOS: Dict[str, str] = {
    'grimoire': "🔮 **Гримуар** — это ваш мистический проводник...",
    'negotiator': "🗣️🎯 **SKILLTRAINER** - проведет интервью, определит навыки для тренировки, запустит сессии в режимах Sim/Drill/Build/Case/Quiz с HUD и гейтами",
    'analyzer': "📈 **Аналитик** — ваш надежный помощник...",
    'coach': "🧘 **Коуч** поможет вам структурировать...",
    'generator': "💡 **Генератор** — это креативный хуб...",
    'editor': "📝 **Редактор** — ваш личный корректор...",
    'marketer': "🎯 **Маркетолог** — ваш наставник...",
    'hr': "🚀 **HR-рекрутер** помогает соискателям...",
    'skilltrainer': """
🎓 **SKILLTRAINER-Universal** — ваш персональный тренер навыков.
🔹 Проходит с вами короткое интервью (7 вопросов)  
🔹 Определяет, какой навык стоит прокачать  
🔹 Предлагает 5 режимов: Sim / Drill / Build / Case / Quiz  
🔹 Работает пошагово с HUD и гейтами (DOD)  
🔹 Даёт короткие подсказки (HINTS ≤240 символов)  
🔹 Формирует **Finish Packet** с рекомендациями  
🔹 Предлагает экспорт результатов
💡 Идеально для: переговоров, продаж, саморегуляции, публичных выступлений, лидерства.
"""
}

SKILLTRAINER_QUESTIONS = [
    "🎯 **Шаг 1/7:** Какой конкретный навык вы хотите развить? (Например: 'ведение сложных переговоров', 'уверенные публичные выступления', 'эффективное тайм-менеджмент')",
    "📊 **Шаг 2/7:** По шкале от 1 до 10, где вы сейчас находитесь? (1 - полный новичок, 10 - эксперт)",
    "🎭 **Шаг 3/7:** В каких реальных ситуациях вы чаще всего применяете или будете применять этот навык?",
    "💪 **Шаг 4/7:** Какая часть этого навыка дается вам сложнее всего? Что вызывает трудности?",
    "🎯 **Шаг 5/7:** Какой конкретный результат вы хотите получить после тренировки? (Измеримая цель)",
    "🔄 **Шаг 6/7:** Сколько времени в неделю вы готовы уделять практике?",
    "🚀 **Шаг 7/7:** Отлично! Все ответы записаны. Теперь выберите режим тренировки:"
]

TRAINING_MODE_DESCRIPTIONS = {
    "sim": "🎭 **SIM (Симуляция)**: Практика в реалистичных смоделированных ситуациях. Идеально для отработки навыков в безопасной среде.",
    "drill": "💪 **DRILL (Отработка)**: Многократное повторение конкретных техник и приемов. Для доведения действий до автоматизма.",
    "build": "🏗️ **BUILD (Построение)**: Поэтапное создание стратегии или системы. Для комплексных навыков, требующих структуры.",
    "case": "📋 **CASE (Кейс)**: Разбор реальных или гипотетических кейсов. Для развития аналитического мышления.",
    "quiz": "❓ **QUIZ (Тест)**: Проверка знаний через вопросы и сценарии. Для закрепления теории и быстрой проверки понимания."
}

SKILLTRAINER_GATES = {
    "interview_complete": {
        "id": "interview_complete",
        "description": "✅ Даны развернутые ответы на все 7 вопросов диагностики",
        "validate": lambda session: len(session.answers) >= 7 and all(len(str(v)) > 5 for v in session.answers.values())
    },
    "mode_selected": {
        "id": "mode_selected", 
        "description": "✅ Выбран режим тренировки (Sim/Drill/Build/Case/Quiz)",
        "validate": lambda session: session.selected_mode is not None
    },
    "training_complete": {
        "id": "training_complete",
        "description": "✅ Пройдена как минимум одна тренировочная сессия",
        "validate": lambda session: session.training_complete
    }
}

# ==============================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==============================================================================
def sanitize_user_input(text: str, max_length: int = 2000) -> str:
    if not text:
        return ""
    cleaned = ''.join(char for char in text if char.isprintable() or char in '\n\r\t')
    return cleaned[:max_length]

def split_message_efficiently(text: str, max_length: int = 4096) -> List[str]:
    if len(text) <= max_length:
        return [text]
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
    final_parts = []
    for part in parts:
        if len(part) > max_length:
            for i in range(0, len(part), max_length):
                final_parts.append(part[i:i+max_length])
        else:
            final_parts.append(part)
    return final_parts

def get_calculator_data_safe(context, index: int, default: float = 0.0) -> float:
    data = context.user_data.get('calculator_data', {})
    return data.get(index, default)

def generate_hud(session: SkillSession) -> str:
    filled = int(session.progress * 10)
    progress_bar = f"[{'█' * filled}{'▒' * (10 - filled)}]"
    hud_lines = [
        f"{progress_bar} {int(session.progress * 100)}%",
        f"Шаг {session.current_step + 1}/{session.max_steps}",
    ]
    if session.selected_mode:
        hud_lines.append(f"Режим: {session.selected_mode.name}")
    if session.gates_passed:
        hud_lines.append(f"Гейты: {len(session.gates_passed)}/{len(SKILLTRAINER_GATES)}")
    return " | ".join(hud_lines)

def generate_hint(session: SkillSession, context: str = "") -> str:
    hints_library = [
        "💡 Совет: Будьте конкретнее в ответах. Вместо 'хочу лучше общаться' попробуйте 'хочу научиться задавать открытые вопросы в диалоге'.",
        "💡 Напоминание: Регулярность важнее длительности. Лучше 15 минут ежедневно, чем 2 часа раз в неделю.",
        "💡 Подсказка: Сфокусируйтесь на одном микро-навыке за раз. Разбейте большую цель на маленькие достижимые шаги.",
        "💡 Идея: Записывайте свои успехи. Даже маленькие победы создают прогресс и мотивацию.",
        "💡 Метод: Используйте технику '5 почему' чтобы докопаться до корня проблемы с навыком."
    ]
    if context and "сложн" in context.lower():
        return "💡 Если сложно: Начните с самого простого действия. Даже 2 минуты практики лучше, чем ничего."
    import random
    hint = random.choice(hints_library)
    if len(hint) > 240:
        hint = hint[:237] + "..."
    return hint

def check_gate(session: SkillSession, gate_id: str) -> tuple[bool, str]:
    if gate_id not in SKILLTRAINER_GATES:
        return False, f"Неизвестный гейт: {gate_id}"
    gate = SKILLTRAINER_GATES[gate_id]
    is_passed = gate["validate"](session)
    if is_passed:
        session.pass_gate(gate_id)
        return True, f"✅ {gate['description']}"
    else:
        return False, f"⏳ {gate['description']}"

def format_finish_packet(session: SkillSession, ai_response: str) -> str:
    packet = f"""
🎓 **FINISH PACKET - SKILLTRAINER {SKILLTRAINER_VERSION}**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**📅 Сессия завершена:** {datetime.now().strftime('%d.%m.%Y %H:%M')}
**👤 Пользователь ID:** {session.user_id}
**🎯 Режим тренировки:** {session.selected_mode.name if session.selected_mode else 'Не выбран'}
**📊 Прогресс:** {int(session.progress * 100)}%
**🔍 КЛЮЧЕВЫЕ ОТВЕТЫ:**
"""
    for step, answer in session.answers.items():
        if step < len(SKILLTRAINER_QUESTIONS):
            packet += f"\n{SKILLTRAINER_QUESTIONS[step].split('**Шаг')[1].split(':**')[0]}:\n{answer}\n"
    packet += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    packet += f"**🎯 ПЕРСОНАЛИЗИРОВАННАЯ ПРОГРАММА:**\n{ai_response}\n"
    packet += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    packet += f"**📋 ПРОЙДЕННЫЕ ГЕЙТЫ:** {len(session.gates_passed)}/{len(SKILLTRAINER_GATES)}\n"
    for gate_id in session.gates_passed:
        packet += f"• {SKILLTRAINER_GATES[gate_id]['description']}\n"
    if session.last_hint:
        packet += f"\n**💡 ПОСЛЕДНЯЯ ПОДСКАЗКА:**\n• {session.last_hint}\n"
    else:
        packet += f"\n**💡 ПОДСКАЗКИ НЕ ЗАПРАШИВАЛИСЬ**\n"
    packet += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    packet += f"**🚀 СЛЕДУЮЩИЕ ШАГИ:**\n"
    packet += f"1. Повторите основные техники в течение недели\n"
    packet += f"2. Отметьте 3 ситуации, где применили навык\n"
    packet += f"3. Вернитесь через 7 дней для оценки прогресса\n"
    return packet

# ==============================================================================
# 5. GROWTH, КАЛЬКУЛЯТОР, GROQ — стандартные функции (без изменений)
# ==============================================================================
async def get_usage_stats(user_id: int) -> Dict[str, Any]:
    if user_id not in user_stats_cache:
        user_stats_cache.set(user_id, {
            'tools_used': 0,
            'ai_requests': 0,
            'calculator_uses': 0,
            'skilltrainer_sessions': 0,
            'first_seen': datetime.now(),
            'last_active': datetime.now(),
            'ab_test_group': 'A' if user_id % 2 == 0 else 'B'
        })
    stats = user_stats_cache.get(user_id)
    stats['last_active'] = datetime.now()
    user_stats_cache.set(user_id, stats)
    return stats

async def update_usage_stats(user_id: int, tool_type: str):
    stats = await get_usage_stats(user_id)
    if tool_type == 'ai':
        stats['ai_requests'] += 1
    elif tool_type == 'calculator':
        stats['calculator_uses'] += 1
    elif tool_type == 'skilltrainer':
        stats['skilltrainer_sessions'] = stats.get('skilltrainer_sessions', 0) + 1
    tools_used = set()
    if stats['ai_requests'] > 0:
        tools_used.add('ai')
    if stats['calculator_uses'] > 0:
        tools_used.add('calculator')
    if stats.get('skilltrainer_sessions', 0) > 0:
        tools_used.add('skilltrainer')
    stats['tools_used'] = len(tools_used)
    stats['last_tool'] = tool_type
    user_stats_cache.set(user_id, stats)

async def show_usage_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    stats = await get_usage_stats(user_id)
    tools_progress = "▰" * min(stats['tools_used'], 5) + "▱" * (5 - min(stats['tools_used'], 5))
    ai_progress = "▰" * min(stats['ai_requests'] // 3, 5) + "▱" * (5 - min(stats['ai_requests'] // 3, 5))
    progress_text = f"""
📊 **ВАШ ПРОГРЕСС:**
🛠️ Инструменты: {tools_progress} {stats['tools_used']}/5
🤖 AI запросы: {ai_progress} {stats['ai_requests']}+
📈 Калькулятор: {stats['calculator_uses']} использований
🎓 SKILLTRAINER: {stats.get('skilltrainer_sessions', 0)} сессий
🎯 Группа теста: {stats['ab_test_group']}
💡 Исследуйте больше инструментов для увеличения прогресса!
    """
    await update.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)

async def show_referral_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    referral_text = f"""
🎁 **ПРИГЛАСИ ДРУЗЕЙ - ПОЛУЧИ БОНУСЫ!**
Пригласи друга по ссылке:
`{ref_link}`
За каждого друга:
✅ +5 дополнительных AI запросов
✅ Расширенная статистика
✅ Специальные возможности
💬 Просто отправь другу эту ссылку!
    """
    await update.message.reply_text(referral_text, parse_mode=ParseMode.MARKDOWN)

async def get_personal_recommendation(user_id: int) -> str:
    stats = await get_usage_stats(user_id)
    if stats['calculator_uses'] > stats['ai_requests']:
        return "🎯 **Вам подойдет:** Аналитик + Маркетолог (для углубления анализа)"
    elif stats['ai_requests'] > 5:
        return "🎯 **Попробуйте:** Калькулятор для точных финансовых расчетов"
    elif stats.get('skilltrainer_sessions', 0) == 0:
        return "🎯 **Попробуйте:** SKILLTRAINER для структурированного развития навыков"
    else:
        return "🎯 **Начните с:** Быстрый старт в меню 'Для себя'"

def calculate_economy_metrics(data):
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
    data = [get_calculator_data_safe(context, i) for i in range(6)]
    metrics = calculate_economy_metrics(data)
    recommendations = generate_recommendations(metrics)
    report = f"""📊 **ФИНАНСОВЫЙ АНАЛИЗ ТОВАРА**
💰 **ВЫРУЧКА И ЗАТРАТЫ:**
• Выручка: {metrics['выручка']:.1f} ₽
• Себестоимость: {metrics['себестоимость']:.1f} ₽
• Комиссия MP: {metrics['комиссия']:.1f} ₽ ({metrics['комиссия_%']:.1f}%)
• Логистика FBS: {metrics['логистика']:.1f} ₽ ({metrics['логистика_%']:.1f}%)
• Реклама (ACOS): {metrics['реклама']:.1f} ₽ ({metrics['acos_%']:.1f}%)
• Налог УСН: {metrics['налог']:.1f} ₽ ({metrics['налог_%']:.1f}%)
🎯 **УРОВНИ ПРИБЫЛИ:**
• CM1 (до рекламы): {metrics['cm1']:.1f} ₽ ({metrics['маржа_cm1_%']:.1f}%)
• CM2 (после рекламы): {metrics['cm2']:.1f} ₽ ({metrics['маржа_cm2_%']:.1f}%)
• Чистая прибыль: {metrics['чистая_прибыль']:.1f} ₽ ({metrics['чистая_маржа_%']:.1f}%)
📈 **КЛЮЧЕВЫЕ МЕТРИКИ:**
• Наценка: {metrics['наценка_%']:.1f}% {'🚀' if metrics['наценка_%'] > 300 else '✅' if metrics['наценка_%'] > 200 else '📊'}
• Рентабельность: {metrics['чистая_маржа_%']:.1f}% {'✅' if metrics['чистая_маржа_%'] > 30 else '📊'}
💡 **РЕКОМЕНДАЦИИ:**
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
    context.user_data['calculator_step'] = 0
    context.user_data['calculator_data'] = {}
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "🛍️ **РАСЧЕТ ЭКОНОМИКИ МАРКЕТПЛЕЙСА**\n"
            "Введите данные вашего товара:\n"
            + CALCULATOR_STEPS[0],
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🛍️ **РАСЧЕТ ЭКОНОМИКИ МАРКЕТПЛЕЙСА**\n"
            "Введите данные вашего товара:\n"
            + CALCULATOR_STEPS[0],
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_economy_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

async def send_long_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE, 
                          prefix: str = "", parse_mode: str = None):
    parts = split_message_efficiently(text)
    total_parts = len(parts)
    for i, part in enumerate(parts, 1):
        part_prefix = prefix if total_parts == 1 else f"{prefix}*({i}/{total_parts})*\n"
        await context.bot.send_message(chat_id, f"{part_prefix}{part}", parse_mode=parse_mode)

async def handle_groq_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt_key: str):
    if not groq_client or not update.message:
        return
    user_id = update.message.from_user.id
    if not rate_limiter.is_allowed(user_id):
        await update.message.reply_text("🚫 Слишком много запросов. Подождите минуту.")
        return
    user_query = sanitize_user_input(update.message.text)
    system_prompt = SYSTEM_PROMPTS.get(prompt_key, "Вы — полезный ассистент.")
    await update.message.chat.send_message(f"⌛ **{prompt_key.capitalize()}** обрабатывает ваш запрос...", parse_mode=ParseMode.MARKDOWN)
    try:
        cached_response = ai_cache.get_cached_response(prompt_key, user_query)
        if cached_response:
            await send_long_message(
                update.message.chat.id,
                cached_response,
                context,
                prefix=f"🤖 Ответ {prompt_key.capitalize()} (из кэша):\n",
                parse_mode=None
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
        ai_cache.cache_response(prompt_key, user_query, ai_response)
        await send_long_message(
            update.message.chat.id,
            ai_response,
            context,
            prefix=f"🤖 Ответ {prompt_key.capitalize()}:\n",
            parse_mode=None
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

# ==============================================================================
# 6. ОСНОВНОЙ ХЕНДЛЕР
# ==============================================================================
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🏠 Меню"), KeyboardButton("📊 Прогресс")]], 
    one_time_keyboard=False, 
    resize_keyboard=True
)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    user_text = update.message.text.strip()
    user_id = update.message.from_user.id

    if user_text == "🏠 Меню":
        return await start(update, context)
    if user_text == "📊 Прогресс":
        return await progress_command(update, context)

    if user_id in active_skill_sessions:
        session = active_skill_sessions[user_id]
        await handle_skilltrainer_response(update, context, session)
        return context.user_data.get('state', BotState.MAIN_MENU)

    if any(word in user_text.lower() for word in ['пригласи', 'друг', 'реферал', 'ссылка']):
        await show_referral_program(update, context)
        return BotState.MAIN_MENU
    if any(word in user_text.lower() for word in ['прогресс', 'статистика', 'стата']):
        await show_usage_progress(update, context)
        return BotState.MAIN_MENU

    current_state = context.user_data.get('state', BotState.MAIN_MENU)
    if current_state == BotState.CALCULATOR:
        return await handle_economy_calculator(update, context)
    elif context.user_data.get('active_groq_mode'):
        active_mode = context.user_data['active_groq_mode']
        if active_mode in SYSTEM_PROMPTS:
            return await handle_groq_request(update, context, active_mode)
        else:
            await update.message.reply_text("❓ Неизвестный AI режим. Нажмите 🏠 Меню для сброса.")
            return BotState.MAIN_MENU
    elif current_state in (BotState.AI_SELECTION, BotState.BUSINESS_MENU):
        await update.message.reply_text("❓ Вы отправили текст, но не активировали ни один из ИИ-инструментов. Нажмите на кнопку 'Активировать' под нужным инструментом, чтобы начать диалог, или 🏠 Меню для возврата.")
        return current_state
    else:
        help_text = f"""
🤖 **Personal Growth AI** {BOT_VERSION}
💡 **Доступные команды:**
/start - Главное меню  
/progress - Ваш прогресс и статистика
🎯 **Быстрый старт:**
• Напишите "пригласи друга" для реферальной программы
• Используйте "мой прогресс" для статистики
• Выберите инструмент из меню
🚀 **Новый инструмент: SKILLTRAINER**
Многошаговая сессия развития навыков с гейтами и прогресс-баром!
"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        return current_state

# ==============================================================================
# 7. ОСНОВНЫЕ ФУНКЦИИ БОТА
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    if not update.message: 
        return BotState.MAIN_MENU
    user_id = update.message.from_user.id
    if user_id in active_skill_sessions:
        del active_skill_sessions[user_id]
    stats = await get_usage_stats(user_id)
    if stats['ab_test_group'] == 'A':
        inline_keyboard = [
            [InlineKeyboardButton("Для себя (ИИ-инструменты)", callback_data='menu_self')],
            [InlineKeyboardButton("Для дела (Калькуляторы и ИИ-инструменты)", callback_data='menu_business')]
        ]
        welcome_text = "👋 Привет! Выберите инструмент:"
    else:
        inline_keyboard = [
            [InlineKeyboardButton("🧠 Личный рост", callback_data='menu_self')],
            [InlineKeyboardButton("🚀 Бизнес и карьера", callback_data='menu_business')],
            [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')]
        ]
        welcome_text = f"🎯 Добро пожаловать! Ваша группа: {stats['ab_test_group']}\nВыберите направление:"
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    await update.message.reply_text("👋 Привет! Используйте нижнюю панель для навигации.", reply_markup=REPLY_KEYBOARD)
    if stats['tools_used'] > 0:
        await show_usage_progress(update, context)
    await update.message.reply_text(welcome_text, reply_markup=inline_markup)
    context.user_data['state'] = BotState.MAIN_MENU
    context.user_data['active_groq_mode'] = None
    logger.info(f"{BOT_VERSION} - User {user_id} started bot (Group: {stats['ab_test_group']})")
    return BotState.MAIN_MENU

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    return await start(update, context)

async def version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    version_info = f"""
🤖 **Personal Growth AI** {BOT_VERSION}
📊 **КОМПОНЕНТЫ:**
• Архитектура: {BOT_VERSION} (Гибридный бот + Growth + SKILLTRAINER)
• Конфигурация: {CONFIG_VERSION}
• Калькулятор: v1.0 (полный из первого бота)
• AI движок: v2.0 (Groq + 9 инструментов + кэширование)
• SKILLTRAINER: {SKILLTRAINER_VERSION} (полная реализация)
🔄 **ЧТО ВКЛЮЧЕНО:**
✅ Детальный калькулятор маркетплейса (6 шагов)
✅ 9 AI-инструментов с системными промтами (включая SKILLTRAINER)
✅ SKILLTRAINER: 7 шагов диагностики + 5 режимов + гейты + HUD
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
    await show_usage_progress(update, context)
    user_id = update.message.from_user.id
    recommendation = await get_personal_recommendation(user_id)
    await update.message.reply_text(recommendation, parse_mode=ParseMode.MARKDOWN)

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_referral_program(update, context)

# ... остальные функции (show_main_menu, menu_self, menu_business и т.д.) без изменений ...

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
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

async def menu_self(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
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

async def menu_business(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
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
            "🚀 **ДЛЯ ДЕЛА**\nИнструменты для профессионального роста и бизнеса:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🚀 **ДЛЯ ДЕЛА**\nИнструменты для профессионального роста и бизнеса:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

def get_ai_keyboard(prompt_key: str, back_button: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💡 Демо-сценарий (что он умеет?)", callback_data=f'demo_{prompt_key}')],
        [InlineKeyboardButton("✅ Активировать платный доступ (10 кнопок)", callback_data=f'activate_{prompt_key}')],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data='show_progress')],
        [InlineKeyboardButton("🔙 Назад", callback_data=back_button)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def ai_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    prompt_key = callback_data.split('_')[1] 
    context.user_data['current_ai_key'] = prompt_key
    if callback_data.endswith('_self'):
        back_button = 'menu_self'
    else:
        back_button = 'menu_business'
    reply_markup = get_ai_keyboard(prompt_key, back_button)
    await query.edit_message_text(
        f"Вы выбрали **{prompt_key.capitalize()}**.\n"
        f"Чтобы начать, изучите демо-сценарий или активируйте доступ.", 
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['state'] = BotState.AI_SELECTION
    context.user_data['active_groq_mode'] = None
    return BotState.AI_SELECTION

async def show_demo_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    query = update.callback_query
    await query.answer()
    demo_key = query.data.split('_')[1] 
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
    query = update.callback_query
    await query.answer()
    prompt_key = query.data.split('_')[1]
    if prompt_key == 'skilltrainer':
        await start_skilltrainer_session(update, context)
        return BotState.AI_SELECTION
    context.user_data['active_groq_mode'] = prompt_key
    await query.edit_message_text(
        f"✅ Режим **{prompt_key.capitalize()}** активирован!\n"
        f"Напишите ваш первый запрос, и {prompt_key.capitalize()} приступит к работе.\n"
        f"Чтобы сменить режим, используйте команду /start.", 
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['state'] = BotState.AI_SELECTION
    return BotState.AI_SELECTION

async def show_progress_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    stats = await get_usage_stats(user_id)
    tools_progress = "▰" * min(stats['tools_used'], 5) + "▱" * (5 - min(stats['tools_used'], 5))
    ai_progress = "▰" * min(stats['ai_requests'] // 3, 5) + "▱" * (5 - min(stats['ai_requests'] // 3, 5))
    progress_text = f"""
📊 **ВАШ ПРОГРЕСС:**
🛠️ Инструменты: {tools_progress} {stats['tools_used']}/5
🤖 AI запросы: {ai_progress} {stats['ai_requests']}+
📈 Калькулятор: {stats['calculator_uses']} использований
🎓 SKILLTRAINER: {stats.get('skilltrainer_sessions', 0)} сессий
🎯 Группа теста: {stats['ab_test_group']}
💡 Исследуйте больше инструментов для увеличения прогресса!
    """
    await query.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)
    recommendation = await get_personal_recommendation(user_id)
    await query.message.reply_text(recommendation, parse_mode=ParseMode.MARKDOWN)
    return context.user_data.get('state', BotState.MAIN_MENU)

async def menu_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotState:
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = BotState.CALCULATOR
    context.user_data['active_groq_mode'] = None
    await start_economy_calculator(update, context)
    return BotState.CALCULATOR

# ==============================================================================
# 8. SKILLTRAINER — ИСПРАВЛЕННЫЙ ХЕНДЛЕР
# ==============================================================================
async def start_skilltrainer_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id in active_skill_sessions:
        del active_skill_sessions[user_id]
    session = SkillSession(user_id)
    active_skill_sessions[user_id] = session
    context.user_data['active_groq_mode'] = None
    logger.info(f"Started SKILLTRAINER session for user {user_id}")
    await send_skilltrainer_question(update, context, session)

async def send_skilltrainer_question(update: Update, context: ContextTypes.DEFAULT_TYPE, session: SkillSession):
    hud = generate_hud(session)
    if session.current_step < len(SKILLTRAINER_QUESTIONS):
        question = SKILLTRAINER_QUESTIONS[session.current_step]
        if session.current_step == 6:
            # 🔹 УБРАНА КНОПКА "НАЗАД"
            keyboard = [
                [InlineKeyboardButton("🎭 Sim", callback_data="st_mode_sim"),
                 InlineKeyboardButton("💪 Drill", callback_data="st_mode_drill"),
                 InlineKeyboardButton("🏗️ Build", callback_data="st_mode_build")],
                [InlineKeyboardButton("📋 Case", callback_data="st_mode_case"),
                 InlineKeyboardButton("❓ Quiz", callback_data="st_mode_quiz"),
                 InlineKeyboardButton("ℹ️ Описания", callback_data="st_mode_info")],
                [InlineKeyboardButton("❌ Отмена", callback_data="st_cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"{hud}\n{question}\n**Выберите режим тренировки:**",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"{hud}\n{question}\n**Выберите режим тренировки:**",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"{hud}\n{question}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"{hud}\n{question}",
                    parse_mode=ParseMode.MARKDOWN
                )
    else:
        await finish_skilltrainer_interview(update, context, session)

async def handle_skilltrainer_response(update: Update, context: ContextTypes.DEFAULT_TYPE, session: SkillSession):
    user_text = update.message.text
    user_id = update.message.from_user.id

    if user_text.lower() in ['отмена', 'cancel', 'стоп', 'stop']:
        if user_id in active_skill_sessions:
            del active_skill_sessions[user_id]
        await update.message.reply_text("❌ Сессия SKILLTRAINER отменена.")
        await show_business_menu_from_callback(update, context)
        return

    if user_text.lower() in ['подсказка', 'hint', 'help']:
        hint = generate_hint(session, user_text)
        session.set_hint(hint)
        await update.message.reply_text(hint)
        return

    session.add_answer(session.current_step, user_text)
    check_gate(session, "interview_complete")

    import random
    if random.random() < 0.3:
        hint = generate_hint(session)
        session.set_hint(hint)
        await update.message.reply_text(hint)

    if session.current_step < len(SKILLTRAINER_QUESTIONS):
        await send_skilltrainer_question(update, context, session)
    else:
        session.state = SessionState.MODE_SELECTION
        await send_skilltrainer_question(update, context, session)

async def handle_skilltrainer_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in active_skill_sessions:
        await query.edit_message_text("❌ Сессия не найдена. Начните заново через меню.")
        return
    session = active_skill_sessions[user_id]
    mode_data = query.data.replace('st_mode_', '')

    if mode_data == 'info':
        descriptions_text = "**📚 ОПИСАНИЯ РЕЖИМОВ ТРЕНИРОВКИ:**\n"
        for mode_id, description in TRAINING_MODE_DESCRIPTIONS.items():
            descriptions_text += f"{description}\n"
        keyboard = [[InlineKeyboardButton("🔙 Назад к выбору", callback_data="st_mode_select")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(descriptions_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    if mode_data == 'select':
        session.current_step = 6
        session.state = SessionState.MODE_SELECTION
        await send_skilltrainer_question(update, context, session)
        return

    if mode_data == 'cancel':
        if user_id in active_skill_sessions:
            del active_skill_sessions[user_id]
        await query.edit_message_text("❌ Сессия SKILLTRAINER отменена.")
        await show_business_menu_from_callback(update, context)
        return

    mode_map = {
        'sim': TrainingMode.SIM,
        'drill': TrainingMode.DRILL,
        'build': TrainingMode.BUILD,
        'case': TrainingMode.CASE,
        'quiz': TrainingMode.QUIZ
    }
    if mode_data in mode_map:
        session.selected_mode = mode_map[mode_data]
        session.current_step = 7
        session.update_progress()
        check_gate(session, "mode_selected")
        await start_training_session(update, context, session)
    else:
        await query.edit_message_text("❓ Неизвестный режим.")

async def start_training_session(update: Update, context: ContextTypes.DEFAULT_TYPE, session: SkillSession):
    hud = generate_hud(session)
    training_prompts = {
        TrainingMode.SIM: f"🎭 **РЕЖИМ: SIM (Симуляция)**\nСейчас я создам реалистичную ситуацию для отработки вашего навыка. Готовы начать симуляцию?",
        TrainingMode.DRILL: f"💪 **РЕЖИМ: DRILL (Отработка)**\nСейчас мы будем отрабатывать конкретные техники. Начнем с базовых упражнений. Готовы?",
        TrainingMode.BUILD: f"🏗️ **РЕЖИМ: BUILD (Построение)**\nСейчас мы построим пошаговую стратегию развития вашего навыка. Начнем с фундамента. Готовы?",
        TrainingMode.CASE: f"📋 **РЕЖИМ: CASE (Кейс)**\nСейчас мы разберем реальный кейс применения вашего навыка. Готовы к анализу?",
        TrainingMode.QUIZ: f"❓ **РЕЖИМ: QUIZ (Тест)**\nСейчас я задам вопросы для проверки ваших знаний. Готовы к тесту?"
    }
    prompt = training_prompts.get(session.selected_mode, "Начинаем тренировку...")
    keyboard = [
        [InlineKeyboardButton("✅ Начать тренировку", callback_data="st_start_training")],
        [InlineKeyboardButton("🔙 Выбрать другой режим", callback_data="st_mode_select")],
        [InlineKeyboardButton("❌ Завершить", callback_data="st_finish_early")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(
        f"{hud}\n{prompt}",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_training_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in active_skill_sessions:
        await query.edit_message_text("❌ Сессия не найдена.")
        return
    session = active_skill_sessions[user_id]
    session.state = SessionState.TRAINING
    if groq_client:
        try:
            answers_text = "\n".join([f"Вопрос {i+1}: {answer}" for i, answer in session.answers.items()])
            training_request = f"""
Пользователь хочет развить навык. Вот его ответы на диагностику:
{answers_text}
Выбранный режим тренировки: {session.selected_mode.name if session.selected_mode else 'Не выбран'}
Создай одно тренировочное задание в выбранном режиме. Задание должно быть:
1. Практическим и конкретным
2. Соответствовать выбранному режиму
3. Иметь четкую инструкцию
4. Быть выполнимым за 5-15 минут
5. Включать критерии успешного выполнения (DOD)
Формат ответа:
**ЗАДАНИЕ:**
[Название задания]
**ИНСТРУКЦИЯ:**
[Пошаговая инструкция]
**КРИТЕРИИ УСПЕХА (DOD):**
1. [Критерий 1]
2. [Критерий 2]
3. [Критерий 3]
**ПОДСКАЗКА:**
[Короткая подсказка ≤240 символов]
"""
            messages = [
                {"role": "system", "content": SYSTEM_PROMPTS['skilltrainer']},
                {"role": "user", "content": training_request}
            ]
            await query.edit_message_text(f"{generate_hud(session)}\n🎯 Генерирую задание...")
            chat_completion = groq_client.chat.completions.create(
                messages=messages,
                model="llama-3.1-8b-instant",
                max_tokens=1500
            )
            training_task = chat_completion.choices[0].message.content
            session.data = {'training_task': training_task}
            session.training_complete = True
            check_gate(session, "training_complete")
            keyboard = [
                [InlineKeyboardButton("✅ Задание выполнено", callback_data="st_task_done")],
                [InlineKeyboardButton("💡 Нужна подсказка", callback_data="st_need_hint")],
                [InlineKeyboardButton("🔄 Другое задание", callback_data="st_another_task")],
                [InlineKeyboardButton("🏁 Завершить сессию", callback_data="st_finish_session")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"{generate_hud(session)}\n{training_task}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка генерации задания SKILLTRAINER: {e}")
            await query.edit_message_text(
                f"{generate_hud(session)}\n❌ Ошибка при генерации задания. Попробуйте еще раз или выберите другой режим.",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await query.edit_message_text(
            f"{generate_hud(session)}\n❌ Groq API не доступен. SKILLTRAINER не может работать без AI.",
            parse_mode=ParseMode.MARKDOWN
        )

async def finish_skilltrainer_session(update: Update, context: ContextTypes.DEFAULT_TYPE, session: SkillSession = None):
    if not session:
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        session = active_skill_sessions.get(user_id)
    if not session:
        await update.callback_query.edit_message_text("❌ Сессия не найдена.")
        return
    session.state = SessionState.FINISH
    session.progress = 1.0
    if groq_client:
        try:
            answers_text = "\n".join([f"Шаг {i+1}: {answer}" for i, answer in session.answers.items()])
            finish_request = f"""
На основе диагностики пользователя сформируй Finish Packet (Итоговый пакет).
ДАННЫЕ ПОЛЬЗОВАТЕЛЯ:
{answers_text}
Выбранный режим тренировки: {session.selected_mode.name if session.selected_mode else 'Не выбран'}
СФОРМИРУЙ FINISH PACKET СО СЛЕДУЮЩИМИ РАЗДЕЛАМИ:
1. **КРАТКАЯ ДИАГНОСТИКА** - основные выводы из ответов
2. **РЕКОМЕНДОВАННЫЕ МЕТОДИКИ** - 3-5 конкретных методик для развития навыка
3. **ПЛАН ТРЕНИРОВОК** - понедельный план на 4 недели
4. **ИНСТРУМЕНТЫ И РЕСУРСЫ** - полезные инструменты, книги, курсы
5. **КРИТЕРИИ ПРОГРЕССА** - как отслеживать улучшения
6. **ЧЕК-ЛИСТ ПРОВЕРКИ** - что проверить через 2 недели
Будь конкретным, практичным и мотивирующим.
"""
            messages = [
                {"role": "system", "content": SYSTEM_PROMPTS['skilltrainer']},
                {"role": "user", "content": finish_request}
            ]
            await update.callback_query.edit_message_text(f"{generate_hud(session)}\n🎓 Формирую Finish Packet...")
            chat_completion = groq_client.chat.completions.create(
                messages=messages,
                model="llama-3.1-8b-instant",
                max_tokens=4000
            )
            ai_response = chat_completion.choices[0].message.content
            session.finish_packet = format_finish_packet(session, ai_response)
            await update_usage_stats(session.user_id, 'skilltrainer')
            if session.user_id in active_skill_sessions:
                del active_skill_sessions[session.user_id]
            # 🔹 ФИНАЛЬНОЕ МЕНЮ: ТОЛЬКО 3 КНОПКИ
            keyboard = [
                [InlineKeyboardButton("🎁 Пригласить друга", callback_data="st_referral")],
                [InlineKeyboardButton("🔄 Новая сессия", callback_data="st_new_session")],
                [InlineKeyboardButton("🔙 В меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_long_message(
                update.callback_query.message.chat.id,
                session.finish_packet,
                context,
                prefix="",
                parse_mode=None
            )
            await update.callback_query.message.reply_text(
                "✅ **СЕССИЯ SKILLTRAINER ЗАВЕРШЕНА!**\n"
                "Вы можете пригласить друга или начать новую сессию.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка генерации Finish Packet: {e}")
            await update.callback_query.edit_message_text(
                "❌ Ошибка при формировании Finish Packet. Основные результаты сохранены.\n"
                f"Ваши ответы: {len(session.answers)} из 7\n"
                f"Режим: {session.selected_mode.name if session.selected_mode else 'Не выбран'}",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.callback_query.edit_message_text(
            "❌ Groq API не доступен. Не могу сформировать Finish Packet.\n"
            "Ваши ответы сохранены. Попробуйте позже.",
            parse_mode=ParseMode.MARKDOWN
        )

# ==============================================================================
# 9. ГЛАВНЫЙ ХЕНДЛЕР ДЕЙСТВИЙ — С ИСПРАВЛЕНИЕМ
# ==============================================================================
async def handle_skilltrainer_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data

    # 🔹 ОБРАБОТКА БЕЗ СЕССИИ
    if action == "st_referral":
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        await query.message.reply_text(
            f"🎁 **Пригласите друга — получите бонусы!**\n\n"
            f"Ваша ссылка:\n`{ref_link}`\n\n"
            "Просто отправьте её другу в Telegram!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if action == "st_new_session":
        await start_skilltrainer_session(update, context)
        return

    # 🔹 ОСТАЛЬНЫЕ ДЕЙСТВИЯ — ТОЛЬКО С АКТИВНОЙ СЕССИЕЙ
    if user_id not in active_skill_sessions:
        await query.edit_message_text("❌ Сессия не найдена.")
        return

    session = active_skill_sessions[user_id]

    if action == "st_task_done":
        await query.edit_message_text(
            f"{generate_hud(session)}\n"
            "✅ **Отлично! Задание выполнено.**\n"
            "Хотите получить еще одно задание или завершить сессию?",
            parse_mode=ParseMode.MARKDOWN
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Еще задание", callback_data="st_another_task")],
            [InlineKeyboardButton("🏁 Завершить сессию", callback_data="st_finish_session")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    elif action == "st_need_hint":
        hint = generate_hint(session)
        session.set_hint(hint)
        await query.message.reply_text(hint)
    elif action == "st_another_task":
        await start_training_session(update, context, session)
    elif action == "st_finish_early":
        await finish_skilltrainer_session(update, context, session)
    elif action == "st_finish_session":
        await finish_skilltrainer_session(update, context, session)

async def finish_skilltrainer_interview(update: Update, context: ContextTypes.DEFAULT_TYPE, session: SkillSession):
    session.state = SessionState.MODE_SELECTION
    await send_skilltrainer_question(update, context, session)

# ==============================================================================
# 10. ЗАПУСК
# ==============================================================================
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN не установлен. Запуск невозможен.")
    application = None
else:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("version", version_command))
    application.add_handler(CommandHandler("progress", progress_command))
    application.add_handler(CommandHandler("referral", referral_command))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(menu_self, pattern='^menu_self$'))
    application.add_handler(CallbackQueryHandler(menu_business, pattern='^menu_business$'))
    application.add_handler(CallbackQueryHandler(menu_calculator, pattern='^menu_calculator$'))
    application.add_handler(CallbackQueryHandler(ai_selection_handler, pattern='^ai_.*_self$|^ai_.*_business$'))
    application.add_handler(CallbackQueryHandler(show_demo_scenario, pattern='^demo_.*$'))
    application.add_handler(CallbackQueryHandler(activate_access, pattern='^activate_.*$'))
    application.add_handler(CallbackQueryHandler(show_progress_handler, pattern='^show_progress$'))
    application.add_handler(CallbackQueryHandler(handle_skilltrainer_mode, pattern='^st_mode_.+$'))
    application.add_handler(CallbackQueryHandler(handle_training_start, pattern='^st_start_training$'))
    application.add_handler(CallbackQueryHandler(handle_skilltrainer_actions, pattern='^st_.+$'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

async def telegram_webhook_handler(request: web.Request) -> web.Response:
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
            logger.info(f"{BOT_VERSION} - Starting bot with SKILLTRAINER and security improvements...")
            asyncio.run(init_webhook_and_start_server(application))
        except KeyboardInterrupt:
            logger.info(f"{BOT_VERSION} - Бот остановлен вручную.")
        except Exception as e:
            logger.error(f"{BOT_VERSION} - Критическая ошибка при запуске бота: {e}")
