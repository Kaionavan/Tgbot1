import json
import asyncio
import logging
import os
import re
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

# =============================================
#  API KEYS
# =============================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
COHERE_KEY = os.getenv("COHERE_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
SERPER_KEY = os.getenv("SERPER_API_KEY", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://kaionavan.github.io/Tgbot1/")
WEATHER_KEY = os.getenv("WEATHER_API_KEY", "7d2fe9b0de0b0dc5c9db043f5705f1a7")
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "AQ.Ab8RN6IUxZwllKer_PjKZzma2BpDldoRR0QMDwWNKgg4b5V6Qg")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "sk_4f36ded5d3261c33de95f257934a1246f2e956d699767a13")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))  # твой chat_id для утренней рассылки

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не задан!")

# =============================================
#  FILES
# =============================================
DATA_FILE = "data.json"
REMINDERS_FILE = "reminders.json"

# =============================================
#  LOGGING
# =========================================23
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================
#  TEMPLATES
# =============================================
TEMPLATES = {
    "🌐 Сайт": "Напиши полный HTML файл с красивым CSS дизайном и JS, всё в одном файле. Сделай: ",
    "🐍 Python": "Напиши полный рабочий Python код без сокращений. Задача: ",
    "🤖 Telegram бот": "Напиши полный код Telegram бота на Python. Бот должен: ",
    "🎮 Игра": "Напиши полную игру на Python или HTML/JS. Игра: ",
    "📱 Приложение": "Напиши полное приложение, весь код целиком. Приложение: ",
    "🗄️ База данных": "Напиши Python код с SQLite базой данных. Функционал: ",
    "🎯 C++": "Напиши полный рабочий C++ код. Задача: ",
    "⚡ JavaScript": "Напиши полный JavaScript код в одном файле. Задача: ",
    "📚 Объяснить": "Объясни простым языком с примерами: ",
    "🔍 Поиск": "Найди актуальную информацию в интернете про: ",
}

# =============================================
#  KEYBOARDS
# =============================================
def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура с кнопками"""
    webapp_url = WEBAPP_URL + ("?groq=" + GROQ_KEY if GROQ_KEY else "")
    keyboard = [
        [KeyboardButton("🎙 Голосовой агент", web_app=WebAppInfo(url=webapp_url))],
        [KeyboardButton("💬 Новый чат"), KeyboardButton("📂 Мои чаты")],
        [KeyboardButton("📋 Шаблоны"), KeyboardButton("🔍 Поиск")],
        [KeyboardButton("🌤 Погода"), KeyboardButton("🔗 Пересказ ссылки")],
        [KeyboardButton("📄 Анализ файла"), KeyboardButton("⏰ Напоминания")],
        [KeyboardButton("📡 Статус AI"), KeyboardButton("❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        persistent=True,
        input_field_placeholder="Выбери действие или напиши сообщение..."
    )

# =============================================
#  DATA MANAGEMENT
# =============================================
def load_data() -> Dict[str, Any]:
    """Загружает данные из файла data.json"""
    if Path(DATA_FILE).exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    # Структура по умолчанию
    return {
        "current": "main",
        "chats": {
            "main": {
                "name": "Основной чат",
                "history": [],
                "created": datetime.now().strftime("%d.%m.%Y")
            }
        },
        "topics": [],
        "last_code": ""
    }

def save_data(data: Dict[str, Any]) -> None:
    """Сохраняет данные в файл data.json"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_reminders() -> List[Dict[str, Any]]:
    """Загружает напоминания из файла reminders.json"""
    if Path(REMINDERS_FILE).exists():
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading reminders: {e}")
    return []

def save_reminders(reminders: List[Dict[str, Any]]) -> None:
    """Сохраняет напоминания в файл reminders.json"""
    try:
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(reminders, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving reminders: {e}")

def get_current_history(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Возвращает историю текущего чата"""
    return data["chats"][data["current"]]["history"]

def add_message(data: Dict[str, Any], role: str, text: str) -> None:
    """Добавляет сообщение в историю текущего чата"""
    history = get_current_history(data)
    history.append({
        "role": role,
        "text": text[:500],  # Ограничиваем длину
        "time": datetime.now().strftime("%d.%m %H:%M")
    })
    # Храним только последние 50 сообщений
    if len(history) > 50:
        data["chats"][data["current"]]["history"] = history[-50:]

def build_context(data: Dict[str, Any]) -> str:
    """Строит контекст для AI из истории и тем"""
    history = get_current_history(data)[-8:]  # Последние 8 сообщений
    
    history_text = "\n".join([
        f"{msg['role']}: {msg['text']}" 
        for msg in history
    ])
    
    topics = ", ".join(data["topics"][-10:]) if data["topics"] else "пока ничего"
    chat_name = data["chats"][data["current"]]["name"]
    last_code = data.get("last_code", "")
    
    code_context = f"\nПоследний код (контекст):\n{last_code[:400]}" if last_code else ""
    
    return (
        f"Ты профессиональный AI-агент и разработчик. Обращайся к пользователю уважительно — господин или сэр. Отвечай на русском языке.\n"
        f"Чат: {chat_name} | Изученные темы: {topics}\n"
        f"История диалога:\n{history_text}{code_context}\n"
        f"ВАЖНО: Если пишешь код - пиши ПОЛНОСТЬЮ без сокращений и заглушек!"
    )

def build_code_prompt(task: str) -> str:
    """Строит промпт для генерации кода"""
    return (
        f"Задача: {task}\n\n"
        f"ТРЕБОВАНИЯ К КОДУ:\n"
        f"1. Напиши ПОЛНЫЙ код от первой до последней строки\n"
        f"2. НЕ используй заглушки типа # TODO или # здесь ваш код\n"
        f"3. Добавь все необходимые импорты\n"
        f"4. Код должен запускаться без изменений\n"
        f"5. Добавь обработку ошибок\n"
        f"6. Комментарии на русском языке\n"
        f"7. Весь код должен быть в одном файле\n"
        f"8. Минимум 50 строк кода\n\n"
        f"Напиши код:"
    )

def extract_code_from_text(text: str) -> Optional[str]:
    """Извлекает код из текста (между ```)"""
    # Ищем блоки кода
    patterns = [
        r'```(?:\w+)?\n(.*?)```',
        r'```(.*?)```',
        r'`(.*?)`',
    ]
    
    for pattern in patterns:
        codes = re.findall(pattern, text, re.DOTALL)
        if codes:
            # Берем самый длинный блок
            best = max(codes, key=len).strip()
            if len(best) > 50:  # Минимальная длина кода
                return best
    
    return None

def detect_extension(prompt: str, code: str) -> str:
    """Определяет расширение файла по промпту и коду"""
    prompt_lower = prompt.lower()
    
    # По промпту
    if any(x in prompt_lower for x in ['html', 'сайт', 'веб-страница', 'веб страница']):
        return 'html'
    if 'css' in prompt_lower:
        return 'css'
    if any(x in prompt_lower for x in ['javascript', 'js', 'скрипт']):
        return 'js'
    if any(x in prompt_lower for x in ['c++', 'cpp', 'плюсы']):
        return 'cpp'
    if any(x in prompt_lower for x in ['c#', 'csharp', 'шарп']):
        return 'cs'
    if 'kotlin' in prompt_lower:
        return 'kt'
    if 'swift' in prompt_lower:
        return 'swift'
    if 'rust' in prompt_lower:
        return 'rs'
    if any(x in prompt_lower for x in ['golang', 'go ']):
        return 'go'
    if 'php' in prompt_lower:
        return 'php'
    if 'ruby' in prompt_lower:
        return 'rb'
    if any(x in prompt_lower for x in ['bash', 'shell', 'sh']):
        return 'sh'
    if 'sql' in prompt_lower:
        return 'sql'
    if any(x in prompt_lower for x in ['dart', 'flutter']):
        return 'dart'
    if 'java' in prompt_lower and 'javascript' not in prompt_lower:
        return 'java'
    
    # По содержимому кода
    if code:
        if '#include' in code or 'cout' in code or 'using namespace' in code:
            return 'cpp'
        if 'using System' in code or 'namespace' in code and 'class' in code:
            return 'cs'
        if 'console.log' in code or 'function' in code and 'var' in code:
            return 'js'
        if '<html' in code or '<!DOCTYPE' in code:
            return 'html'
        if 'def ' in code and 'import' in code:
            return 'py'
        if 'package main' in code and 'func main' in code:
            return 'go'
        if '<?php' in code:
            return 'php'
        if 'CREATE TABLE' in code or 'SELECT * FROM' in code:
            return 'sql'
    
    # По умолчанию
    return 'py'

def is_code_request(text: str) -> bool:
    """Проверяет, просит ли пользователь код"""
    keywords = [
        "создай", "напиши", "сделай", "код", "приложение", "скрипт",
        "программу", "бот", "сайт", "функцию", "калькулятор", "игру",
        "база данных", "класс", "алгоритм", "парсер", "api"
    ]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)

def is_search_request(text: str) -> bool:
    """Проверяет, просит ли пользователь поиск"""
    keywords = [
        "найди", "поищи", "что сейчас", "новости", "актуально", 
        "курс", "погода", "цена", "кто такой", "что такое", "где"
    ]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)

# =============================================
#  AI PROVIDERS
# =============================================
async def ask_groq(prompt: str, system_context: str) -> Optional[str]:
    """Запрос к Groq API"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_context},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 8000,
                    "temperature": 0.3
                }
            )
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

async def ask_gemini(prompt: str, system_context: str) -> Optional[str]:
    """Запрос к Gemini API"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": f"{system_context}\n\n{prompt}\n\nПиши ПОЛНЫЙ код без сокращений!"}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "maxOutputTokens": 8192,
                        "temperature": 0.3
                    }
                }
            )
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return None

async def ask_openrouter(prompt: str, system_context: str) -> Optional[str]:
    """Запрос к OpenRouter API"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek/deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_context},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 8000
                }
            )
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return None

async def ask_cohere(prompt: str, system_context: str) -> Optional[str]:
    """Запрос к Cohere API"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.cohere.ai/v1/chat",
                headers={
                    "Authorization": f"Bearer {COHERE_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "command-r-plus",
                    "message": prompt,
                    "preamble": system_context,
                    "max_tokens": 4000
                }
            )
            data = response.json()
            return data["text"]
    except Exception as e:
        logger.error(f"Cohere error: {e}")
        return None

async def ask_deepseek(prompt: str, system_context: str) -> Optional[str]:
    """Запрос к DeepSeek API"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_context},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 8000
                }
            )
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return None

async def get_best_ai_response(prompt: str, system_context: str, for_code: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Пробует провайдеров по очереди, пока не получит ответ"""
    
    # Очередность провайдеров в зависимости от типа запроса
    providers = [
        (ask_groq, "Groq"),
        (ask_cohere, "Cohere"),
        (ask_openrouter, "OpenRouter"),
        (ask_gemini, "Gemini"),
        (ask_deepseek, "DeepSeek"),
    ]
    
    for provider_func, provider_name in providers:
        try:
            result = await provider_func(prompt, system_context)
            if result:
                logger.info(f"Got response from {provider_name}")
                return result, provider_name
        except Exception as e:
            logger.error(f"{provider_name} error: {e}")
            continue
    
    return None, None

async def generate_code_smart(task: str, system_context: str) -> Tuple[Optional[str], Optional[str]]:
    """Умная генерация кода с проверкой длины"""
    
    # Первая попытка
    result, ai_name = await get_best_ai_response(
        build_code_prompt(task), 
        system_context, 
        for_code=True
    )
    
    if not result:
        return None, None
    
    # Извлекаем код
    code = extract_code_from_text(result)
    
    # Если код слишком короткий, просим дописать
    if code and len(code) < 800:
        expand_prompt = (
            f"Код слишком короткий. Задача: {task}\n\n"
            f"Предыдущий код:\n```\n{code}\n```\n\n"
            f"Допиши код полностью - добавь все функции, UI, обработку ошибок. "
            f"Напиши весь код заново, но теперь ПОЛНОСТЬЮ, минимум 100 строк!"
        )
        
        result2, ai_name2 = await get_best_ai_response(
            expand_prompt,
            system_context,
            for_code=True
        )
        
        if result2 and len(result2) > len(result):
            return result2, f"{ai_name}+доп"
    
    return result, ai_name

async def check_all_providers() -> Dict[str, str]:
    """Параллельная проверка всех провайдеров"""
    
    test_prompt = "Скажи 'ок' одним словом"
    test_context = "Ты помощник. Отвечай кратко."
    
    providers = [
        ("🟢 Groq", ask_groq),
        ("💎 Gemini", ask_gemini),
        ("🔷 OpenRouter", ask_openrouter),
        ("🟡 Cohere", ask_cohere),
        ("🔵 DeepSeek", ask_deepseek),
    ]
    
    async def check_provider(name: str, func: callable) -> Tuple[str, str]:
        try:
            result = await asyncio.wait_for(func(test_prompt, test_context), timeout=8)
            if result:
                return name, "✅ Работает"
            else:
                return name, "❌ Нет ответа"
        except asyncio.TimeoutError:
            return name, "⏱ Таймаут"
        except Exception:
            return name, "❌ Ошибка"
    
    results = await asyncio.gather(*[
        check_provider(name, func) for name, func in providers
    ])
    
    return dict(results)

# =============================================
#  VOICE AND IMAGE PROCESSING
# =============================================
async def transcribe_voice(audio_data: bytes) -> str:
    """Распознаёт голос через Groq Whisper"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files={
                    "file": ("audio.ogg", audio_data, "audio/ogg"),
                    "model": (None, "whisper-large-v3"),
                    "language": (None, "ru"),
                    "response_format": (None, "json")
                }
            )
            data = r.json()
            text = data.get("text", "").strip()
            if text:
                logger.info(f"Voice transcribed: {text[:50]}")
                return text
    except Exception as e:
        logger.error(f"Whisper error: {e}")

    # Fallback — пробуем без указания языка
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files={
                    "file": ("audio.mp3", audio_data, "audio/mpeg"),
                    "model": (None, "whisper-large-v3"),
                }
            )
            return r.json().get("text", "").strip()
    except Exception as e:
        logger.error(f"Whisper fallback error: {e}")
    return ""


async def analyze_image(image_bytes: bytes, prompt: str = "") -> Optional[str]:
    """Анализирует изображение через Groq Vision (llama-4-scout)"""
    import base64
    b64 = base64.b64encode(image_bytes).decode()
    question = prompt or "Опиши подробно что видишь на изображении. Если есть текст — прочитай его весь. Отвечай на русском языке."

    # Способ 1: Groq Vision — llama-4-scout
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": question}
                    ]}],
                    "max_tokens": 1024
                }
            )
            data = r.json()
            if "choices" in data:
                result = data["choices"][0]["message"]["content"]
                if result and len(result) > 5:
                    logger.info("✅ Image analyzed via Groq Vision")
                    return result
            logger.error(f"Groq vision response: {data}")
    except Exception as e:
        logger.error(f"Groq vision error: {e}")

    # Способ 2: Gemini напрямую как резерв
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    {"text": question}
                ]}]}
            )
            data = r.json()
            if "candidates" in data:
                result = data["candidates"][0]["content"]["parts"][0]["text"]
                logger.info("✅ Image analyzed via Gemini")
                return result
            logger.error(f"Gemini vision: {data.get('error', data)}")
    except Exception as e:
        logger.error(f"Gemini vision error: {e}")

    return None


async def search_web(query: str) -> str:
    """Поиск в интернете через Serper API"""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": SERPER_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "q": query,
                    "gl": "ru",
                    "hl": "ru",
                    "num": 5
                }
            )
            
            data = response.json()
            
            result_parts = []
            
            # Ответ от Google (быстрые ответы)
            if "answerBox" in data:
                answer_box = data["answerBox"]
                if "answer" in answer_box:
                    result_parts.append(f"📌 {answer_box['answer']}")
                elif "snippet" in answer_box:
                    result_parts.append(f"📌 {answer_box['snippet']}")
            
            # Органические результаты
            if "organic" in data:
                for item in data["organic"][:4]:
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    if title and snippet:
                        result_parts.append(f"• *{title}*\n{snippet}")
                    elif snippet:
                        result_parts.append(f"• {snippet}")
            
            if result_parts:
                return "\n\n".join(result_parts)
            else:
                return "По вашему запросу ничего не найдено."
                
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Ошибка при поиске: {e}"

# =============================================
#  REMINDERS
# =============================================
def parse_reminder_time(text: str) -> Tuple[Optional[datetime], str]:
    """Парсит время из текста напоминания"""
    now = datetime.now()
    text_lower = text.lower()
    
    # Шаблоны для поиска времени
    patterns = [
        # через X минут
        (r'через (\d+)\s*минут', lambda m: now + timedelta(minutes=int(m.group(1)))),
        # через X час/часа/часов
        (r'через (\d+)\s*час', lambda m: now + timedelta(hours=int(m.group(1)))),
        # через X день/дня/дней
        (r'через (\d+)\s*дн', lambda m: now + timedelta(days=int(m.group(1)))),
        # завтра в HH:MM
        (r'завтра в (\d{1,2}):(\d{2})', lambda m: (now + timedelta(days=1)).replace(
            hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)),
        # в HH:MM (сегодня или завтра)
        (r'в (\d{1,2}):(\d{2})', lambda m: parse_hhmm(now, int(m.group(1)), int(m.group(2)))),
        # через X часов Y минут
        (r'через (\d+)\s*час(?:ов)?\s*(\d+)\s*минут', 
         lambda m: now + timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))),
    ]
    
    for pattern, func in patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                reminder_time = func(match)
                # Убираем временную часть из текста
                clean_text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
                return reminder_time, clean_text
            except Exception as e:
                logger.error(f"Time parse error: {e}")
                continue
    
    return None, text

def parse_hhmm(now: datetime, hour: int, minute: int) -> datetime:
    """Парсит время в формате HH:MM"""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > now:
        return candidate
    else:
        return candidate + timedelta(days=1)

async def reminder_check_loop(app: Application) -> None:
    """Фоновый цикл проверки напоминаний"""
    while True:
        try:
            reminders = load_reminders()
            now = datetime.now()
            to_keep = []
            
            for reminder in reminders:
                reminder_time = datetime.fromisoformat(reminder["time"])
                if now >= reminder_time:
                    # Отправляем напоминание
                    try:
                        await app.bot.send_message(
                            chat_id=reminder["chat_id"],
                            text=f"⏰ *Напоминание!*\n\n{reminder['text']}",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send reminder: {e}")
                else:
                    to_keep.append(reminder)
            
            if len(to_keep) != len(reminders):
                save_reminders(to_keep)
                
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        
        await asyncio.sleep(60)  # Проверяем каждую минуту

# =============================================
#  MESSAGE SENDING
# =============================================
async def send_long_message(
    bot, 
    chat_id: int, 
    text: str, 
    parse_mode: str = "Markdown"
) -> None:
    """Отправляет длинное сообщение по частям"""
    max_length = 4096
    
    if len(text) <= max_length:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode
            )
        except Exception:
            # Если Markdown не работает, отправляем без форматирования
            await bot.send_message(chat_id=chat_id, text=text)
        return
    
    # Разбиваем на части
    chunks = []
    for i in range(0, len(text), max_length - 500):
        chunk = text[i:i + max_length - 500]
        chunks.append(chunk)
    
    for i, chunk in enumerate(chunks, 1):
        header = f"📄 *Часть {i}/{len(chunks)}:*\n\n"
        full_text = header + chunk
        
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=full_text,
                parse_mode=parse_mode
            )
        except Exception:
            await bot.send_message(chat_id=chat_id, text=full_text)
        
        await asyncio.sleep(0.5)  # Небольшая задержка между частями

# =============================================
#  COMMAND HANDLERS
# =============================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start — всегда отвечает"""
    try:
        data = load_data()
        if "topics" not in data:
            data["topics"] = []
        chat = data["chats"].get(data.get("current", "main"), {"name": "Основной", "history": []})
        
        text = (
            "👑 *Добро пожаловать, господин!*\n\n"
            "Я ваш персональный AI-агент, всегда к вашим услугам.\n\n"
            "📊 *Статус:*\n"
            f"├ 💬 Чат: {chat['name']}\n"
            f"├ 📁 Чатов: {len(data['chats'])}\n"
            f"└ 📚 Тем изучено: {len(data['topics'])}\n\n"
            "🚀 *Мои возможности:*\n"
            "├ 💻 Код на 15+ языках — файлом\n"
            "├ 🎤 Голосовые сообщения\n"
            "├ 📸 Анализ фотографий\n"
            "├ 🌐 Поиск в интернете\n"
            "├ ⏰ Напоминания\n"
            "└ 🤖 5 AI провайдеров\n\n"
            "👇 *Чем могу служить, господин?*"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        logger.error(f"start_command error: {e}")
        try:
            await update.message.reply_text(
                "👑 Приветствую, господин! Готов служить 👇",
                reply_markup=main_keyboard()
            )
        except Exception as e2:
            logger.error(f"start_command fallback error: {e2}")


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /restart"""
    try:
        context.user_data.clear()
        await update.message.reply_text(
            "🔄 *Перезапуск выполнен, господин!*\n\nВсё готово к работе 👇",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logger.error(f"restart error: {e}")
        await update.message.reply_text("🔄 Перезапущен!", reply_markup=main_keyboard())


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /memory"""
    data = load_data()
    current_chat = data["chats"][data["current"]]
    
    # Последние темы
    topics_text = "\n".join([f"• {t}" for t in data["topics"][-15:]]) if data["topics"] else "Пока нет изученных тем"
    
    # Последние сообщения
    recent_messages = []
    for msg in current_chat["history"][-10:]:
        role_icon = "👤" if msg["role"] == "Пользователь" else "🤖"
        recent_messages.append(f"{role_icon} *{msg['time']}*\n{msg['text'][:100]}...")
    
    messages_text = "\n\n".join(recent_messages) if recent_messages else "Нет сообщений"
    
    memory_text = (
        f"🧠 *Память бота*\n\n"
        f"*Текущий чат:* {current_chat['name']}\n"
        f"*Всего сообщений:* {len(current_chat['history'])}\n"
        f"*Всего чатов:* {len(data['chats'])}\n\n"
        f"📚 *Изученные темы (последние 15):*\n{topics_text}\n\n"
        f"💬 *Последние сообщения:*\n\n{messages_text}"
    )
    
    await send_long_message(context.bot, update.effective_chat.id, memory_text)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /clear"""
    data = load_data()
    chat_name = data["chats"][data["current"]]["name"]
    
    # Очищаем историю текущего чата
    data["chats"][data["current"]]["history"] = []
    data["last_code"] = ""
    save_data(data)
    
    await update.message.reply_text(
        f"🗑 Чат *{chat_name}* полностью очищен!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /status"""
    status_msg = await update.message.reply_text(
        "📡 Проверяю все AI провайдеры... Это займет около 8 секунд."
    )
    
    results = await check_all_providers()
    
    status_text = "📡 *Статус AI провайдеров:*\n\n"
    for name, status in results.items():
        status_text += f"{name}: {status}\n"
    
    await status_msg.edit_text(
        status_text,
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = (
        "❓ *Как пользоваться ботом*\n\n"
        "*Основные возможности:*\n"
        "• Отправь голосовое сообщение → распознаю текст\n"
        "• Отправь фото → опишу что на нём\n"
        "• Напиши 'найди ...' → поиск в интернете\n"
        "• Напиши 'напомни через 30 минут ...' → поставлю напоминание\n"
        "• Напиши 'создай игру/сайт/бота' → сгенерирую код\n\n"
        
        "*Команды:*\n"
        "/start - Главное меню со статистикой\n"
        "/restart - Перезапустить бота\n"
        "/status - Проверить статус AI провайдеров\n"
        "/memory - Показать память и историю\n"
        "/clear - Очистить текущий чат\n"
        "/new - Создать новый чат\n"
        "/chats - Управление чатами\n"
        "/search - Поиск в интернете\n"
        "/reminders - Управление напоминаниями\n"
        "/help - Это сообщение\n\n"
        
        "*Кнопки меню:*\n"
        "💬 Новый чат - создать новый диалог\n"
        "📂 Мои чаты - список всех чатов\n"
        "📋 Шаблоны - готовые шаблоны запросов\n"
        "🔍 Поиск - поиск в интернете\n"
        "⏰ Напоминания - управление напоминаниями\n"
        "🧠 Память - показать историю и темы\n"
        "📡 Статус AI - проверить провайдеров\n"
        "❓ Помощь - это сообщение"
    )
    
    await send_long_message(context.bot, update.effective_chat.id, help_text)

async def new_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /new"""
    await update.message.reply_text(
        "✏️ Введите название для нового чата:"
    )
    context.user_data["waiting_for"] = "new_chat_name"

async def chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /chats"""
    data = load_data()
    current = data["current"]
    
    keyboard = []
    for chat_id, chat_info in data["chats"].items():
        mark = "✅ " if chat_id == current else "💬 "
        button_text = f"{mark}{chat_info['name']} ({len(chat_info['history'])} сообщ.)"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"switch_{chat_id}")])
    
    keyboard.append([
        InlineKeyboardButton("➕ Новый чат", callback_data="new_chat"),
        InlineKeyboardButton("🗑 Удалить", callback_data="delete_menu")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💬 *Ваши чаты:*\n\nВыберите чат для переключения:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /search"""
    await update.message.reply_text(
        "🌐 Введите запрос для поиска в интернете:"
    )
    context.user_data["waiting_for"] = "web_search"

async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /reminders"""
    chat_id = update.effective_chat.id
    all_reminders = load_reminders()
    user_reminders = [r for r in all_reminders if r["chat_id"] == chat_id]
    
    keyboard = []
    
    if user_reminders:
        text = "⏰ *Ваши напоминания:*\n\n"
        for i, rem in enumerate(user_reminders[:10]):  # Показываем последние 10
            rem_time = datetime.fromisoformat(rem["time"])
            time_str = rem_time.strftime("%d.%m.%Y в %H:%M")
            text += f"• {rem['text']} — *{time_str}*\n"
            keyboard.append([InlineKeyboardButton(
                f"🗑 Удалить: {rem['text'][:30]}...",
                callback_data=f"delete_reminder_{i}"
            )])
    else:
        text = (
            "⏰ *Напоминания*\n\n"
            "У вас пока нет активных напоминаний.\n\n"
            "*Примеры:*\n"
            "• _напомни через 30 минут позвонить_\n"
            "• _напомни в 15:30 встреча_\n"
            "• _напомни завтра в 10:00 купить хлеб_"
        )
    
    keyboard.append([InlineKeyboardButton("➕ Добавить напоминание", callback_data="add_reminder")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def templates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопки Шаблоны"""
    template_items = list(TEMPLATES.items())
    
    keyboard = []
    # Создаем ряды по 2 кнопки
    for i in range(0, len(template_items), 2):
        row = []
        # Первая кнопка в ряду
        row.append(InlineKeyboardButton(
            template_items[i][0],
            callback_data=f"template_{i}"
        ))
        # Вторая кнопка, если есть
        if i + 1 < len(template_items):
            row.append(InlineKeyboardButton(
                template_items[i + 1][0],
                callback_data=f"template_{i + 1}"
            ))
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 *Выберите шаблон запроса:*\n\n"
        "После выбора скопируйте текст и дополните его.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

# =============================================
#  CALLBACK QUERY HANDLER
# =============================================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на инлайн кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = load_data()
    chat_id = update.effective_chat.id
    
    # Переключение чата
    if data.startswith("switch_"):
        chat_key = data[7:]
        if chat_key in data["chats"]:
            data["current"] = chat_key
            save_data(data)
            await query.edit_message_text(
                f"✅ Переключился на чат: *{data['chats'][chat_key]['name']}*",
                parse_mode="Markdown"
            )
    
    # Меню удаления чатов
    elif data == "delete_menu":
        keyboard = []
        for chat_id_key, chat_info in data["chats"].items():
            if chat_id_key != "main":  # Не даем удалить основной чат
                keyboard.append([InlineKeyboardButton(
                    f"🗑 {chat_info['name']}",
                    callback_data=f"delete_{chat_id_key}"
                )])
        
        if keyboard:
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_chats")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🗑 *Выберите чат для удаления:*\n\nОсновной чат удалить нельзя.",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await query.edit_message_text(
                "❌ Нет чатов для удаления, кроме основного.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="back_to_chats")
                ]])
            )
    
    # Удаление конкретного чата
    elif data.startswith("delete_"):
        chat_key = data[7:]
        if chat_key in data["chats"] and chat_key != "main":
            chat_name = data["chats"][chat_key]["name"]
            del data["chats"][chat_key]
            
            # Если удалили текущий чат, переключаемся на основной
            if data["current"] == chat_key:
                data["current"] = "main"
            
            save_data(data)
            await query.edit_message_text(
                f"🗑 Чат *{chat_name}* успешно удален!",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "❌ Нельзя удалить основной чат!"
            )
    
    # Назад к списку чатов
    elif data == "back_to_chats":
        current = data["current"]
        keyboard = []
        for chat_id_key, chat_info in data["chats"].items():
            mark = "✅ " if chat_id_key == current else "💬 "
            button_text = f"{mark}{chat_info['name']} ({len(chat_info['history'])} сообщ.)"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"switch_{chat_id_key}")])
        
        keyboard.append([
            InlineKeyboardButton("➕ Новый чат", callback_data="new_chat"),
            InlineKeyboardButton("🗑 Удалить", callback_data="delete_menu")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "💬 *Ваши чаты:*\n\nВыберите чат для переключения:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    # Создание нового чата
    elif data == "new_chat":
        await query.edit_message_text(
            "✏️ Введите название для нового чата:"
        )
        context.user_data["waiting_for"] = "new_chat_name"
    
    # Добавление напоминания
    elif data == "add_reminder":
        await query.edit_message_text(
            "⏰ *Создание напоминания*\n\n"
            "Напишите текст напоминания с указанием времени.\n\n"
            "*Примеры:*\n"
            "• _напомни через 30 минут позвонить маме_\n"
            "• _напомни в 15:30 встреча с клиентом_\n"
            "• _напомни завтра в 10:00 купить продукты_",
            parse_mode="Markdown"
        )
        context.user_data["waiting_for"] = "reminder"
    
    # Удаление напоминания
    elif data.startswith("delete_reminder_"):
        try:
            idx = int(data[15:])
            all_reminders = load_reminders()
            user_reminders = [r for r in all_reminders if r["chat_id"] == chat_id]
            
            if idx < len(user_reminders):
                reminder_to_delete = user_reminders[idx]
                all_reminders.remove(reminder_to_delete)
                save_reminders(all_reminders)
                
                await query.edit_message_text(
                    f"🗑 Напоминание *{reminder_to_delete['text']}* удалено!",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text("❌ Напоминание не найдено.")
        except Exception as e:
            logger.error(f"Delete reminder error: {e}")
            await query.edit_message_text("❌ Ошибка при удалении напоминания.")
    
    # Шаблон запроса
    elif data.startswith("template_"):
        try:
            idx = int(data[9:])
            template_keys = list(TEMPLATES.keys())
            if idx < len(template_keys):
                key = template_keys[idx]
                template_text = TEMPLATES[key]
                await query.edit_message_text(
                    f"📋 *{key}*\n\n"
                    f"Скопируйте и дополните запрос:\n\n"
                    f"`{template_text}`",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Template error: {e}")
            await query.edit_message_text("❌ Ошибка при загрузке шаблона.")

# =============================================
#  MESSAGE HANDLERS
# =============================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    # Обработка кнопок главного меню
    if text == "💬 Новый чат":
        await new_chat_command(update, context)
        return
    elif text == "📂 Мои чаты":
        await chats_command(update, context)
        return
    elif text == "📋 Шаблоны":
        await templates_command(update, context)
        return
    elif text == "🔍 Поиск":
        await search_command(update, context)
        return
    elif text == "⏰ Напоминания":
        await reminders_command(update, context)
        return
    elif text == "🧠 Память":
        await memory_command(update, context)
        return
    elif text == "🌤 Погода":
        await weather_command(update, context)
        return
    elif text == "🔗 Пересказ ссылки":
        await summarize_command(update, context)
        return
    elif text == "📄 Анализ файла":
        await update.message.reply_text(
            "Отправь файл (.txt, .pdf, .docx, .csv)\n\n"
            "Добавь подпись к файлу:\n"
            "конспект — краткое содержание\n"
            "викторина — тест с вопросами\n"
            "или без подписи для общего анализа"
        )
        return
    elif text == "📡 Статус AI":
        await status_command(update, context)
        return
    elif text == "❓ Помощь":
        await help_command(update, context)
        return
    
    # Проверяем, ждем ли мы какой-то ввод
    waiting_for = context.user_data.get("waiting_for")
    
    if waiting_for == "new_chat_name":
        # Создаем новый чат
        data = load_data()
        chat_key = f"chat_{int(datetime.now().timestamp())}"
        data["chats"][chat_key] = {
            "name": text,
            "history": [],
            "created": datetime.now().strftime("%d.%m.%Y %H:%M")
        }
        data["current"] = chat_key
        save_data(data)
        
        context.user_data.pop("waiting_for", None)
        
        await update.message.reply_text(
            f"✅ Создан новый чат: *{text}*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return
    
    elif waiting_for == "weather_city":
        context.user_data.pop("waiting_for", None)
        msg = await update.message.reply_text(f"🌤 Ищу погоду для *{text}*...", parse_mode="Markdown")
        data = load_data()
        data["weather_city"] = text
        save_data(data)
        weather = await get_weather(text)
        await msg.edit_text(weather, parse_mode="Markdown")
        return

    elif waiting_for == "summarize_url":
        context.user_data.pop("waiting_for", None)
        import re
        url_match = re.search(r'https?://\S+', text)
        if not url_match:
            await update.message.reply_text("❌ Не нашёл ссылку. Отправь корректный URL начинающийся с http://")
            return
        url = url_match.group(0)
        msg = await update.message.reply_text(f"🔗 Читаю материал...", parse_mode="Markdown")
        result = await summarize_url(url)
        await msg.delete()
        await send_long_message(context.application.bot, chat_id, result, parse_mode="Markdown")
        return

    elif waiting_for == "generate_prompt":
        context.user_data.pop("waiting_for", None)
        msg = await update.message.reply_text("✍️ Создаю промпты...")
        result = await generate_prompt(text)
        await msg.delete()
        await send_long_message(context.application.bot, chat_id, result, parse_mode="Markdown")
        return

    elif waiting_for == "web_search":
        # Выполняем поиск
        context.user_data.pop("waiting_for", None)
        
        search_msg = await update.message.reply_text("🌐 Ищу в интернете...")
        
        # Поиск в интернете
        search_results = await search_web(text)
        
        # Отправляем результаты
        await search_msg.edit_text(
            f"🌐 *Результаты поиска:*\n\n{search_results[:3000]}",
            parse_mode="Markdown"
        )
        
        # Дополнительно спрашиваем AI для краткого ответа
        data = load_data()
        system_context = build_context(data) + f"\n\nРезультаты поиска:\n{search_results}"
        
        thinking = await update.message.reply_text("🤔 Анализирую результаты...")
        
        answer, ai_name = await get_best_ai_response(
            f"На основе результатов поиска дай краткий ответ на вопрос: {text}",
            system_context
        )
        
        if answer:
            await thinking.edit_text(
                f"💡 *Ответ ({ai_name}):*\n\n{answer[:3000]}",
                parse_mode="Markdown"
            )
        else:
            await thinking.delete()
        
        return
    
    elif waiting_for == "reminder":
        # Создаем напоминание
        context.user_data.pop("waiting_for", None)
        
        reminder_time, reminder_text = parse_reminder_time(text)
        
        if reminder_time:
            reminders = load_reminders()
            reminders.append({
                "chat_id": chat_id,
                "text": reminder_text,
                "time": reminder_time.isoformat()
            })
            save_reminders(reminders)
            
            time_str = reminder_time.strftime("%d.%m.%Y в %H:%M")
            await update.message.reply_text(
                f"⏰ *Напоминание установлено!*\n\n"
                f"📝 {reminder_text}\n"
                f"🕐 {time_str}",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось распознать время.\n\n"
                "Используйте формат:\n"
                "• _через 30 минут ..._\n"
                "• _в 15:30 ..._\n"
                "• _завтра в 10:00 ..._",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        return
    
    # Обычное сообщение
    # Проверяем, не напоминание ли это
    if any(word in text.lower() for word in ["напомни", "напоминание"]):
        reminder_time, reminder_text = parse_reminder_time(text)
        if reminder_time:
            reminders = load_reminders()
            reminders.append({
                "chat_id": chat_id,
                "text": reminder_text,
                "time": reminder_time.isoformat()
            })
            save_reminders(reminders)
            
            time_str = reminder_time.strftime("%d.%m.%Y в %H:%M")
            await update.message.reply_text(
                f"⏰ *Напоминание установлено!*\n\n"
                f"📝 {reminder_text}\n"
                f"🕐 {time_str}",
                parse_mode="Markdown"
            )
            return
    
    # Авто-определение погоды
    import re as _re
    _wm = _re.search(r'погод[ауеыи]?\s+(?:в\s+)?([а-яёА-ЯЁ][а-яёА-ЯЁ\s]{1,25})', text.lower())
    if _wm or any(w in text.lower() for w in ["какая погода", "погода сегодня", "погода завтра", "прогноз погоды", "погода в"]):
        _city = _wm.group(1).strip().title() if _wm else load_data().get("weather_city", "Москва")
        _msg = await update.message.reply_text(f"🌤 Получаю погоду для {_city}...")
        _weather = await get_weather(_city)
        _d = load_data(); _d["weather_city"] = _city; save_data(_d)
        await _msg.edit_text(_weather, parse_mode="Markdown")
        return

    # Авто-определение ссылок
    _um = _re.search(r'https?://\S+', text)
    if _um:
        _url = _um.group(0)
        _msg = await update.message.reply_text("🔗 Читаю материал по ссылке...")
        _result = await summarize_url(_url)
        await _msg.delete()
        await send_long_message(context.application.bot, chat_id, _result, parse_mode="Markdown")
        return

    # Авто-определение запроса промпта
    if any(p in text.lower() for p in ["напиши промпт", "создай промпт", "промпт для", "prompt для"]):
        _msg = await update.message.reply_text("✍️ Создаю промпты...")
        _result = await generate_prompt(text)
        await _msg.delete()
        await send_long_message(context.application.bot, chat_id, _result, parse_mode="Markdown")
        return

    # Основная обработка через AI
    data = load_data()
    
    # Сообщаем, что начали работу
    await update.message.reply_text("⚙️ Работаю... Это может занять до 30 секунд.")
    
    # Запускаем обработку в фоне
    asyncio.create_task(process_message(
        context.application,
        chat_id,
        text,
        data,
        update.message.message_id
    ))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик голосовых сообщений"""
    chat_id = update.effective_chat.id
    
    voice_msg = await update.message.reply_text("🎤 Распознаю голосовое сообщение...")
    
    try:
        # Получаем файл голосового сообщения
        file = await context.bot.get_file(update.message.voice.file_id)
        
        # Скачиваем файл правильно
        audio_data = bytes(await file.download_as_bytearray())
        
        # Распознаем текст
        transcribed_text = await transcribe_voice(audio_data)
        
        if transcribed_text:
            await voice_msg.edit_text(
                f"🎤 *Распознано:*\n\n{transcribed_text}",
                parse_mode="Markdown"
            )
            
            # Обрабатываем распознанный текст
            data = load_data()
            asyncio.create_task(process_message(
                context.application,
                chat_id,
                transcribed_text,
                data,
                update.message.message_id
            ))
        else:
            await voice_msg.edit_text("❌ Не удалось распознать голосовое сообщение.")
            
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await voice_msg.edit_text(f"❌ Ошибка при обработке голоса: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик фотографий"""
    chat_id = update.effective_chat.id
    caption = update.message.caption or "Опиши подробно что видишь на этом изображении."
    
    photo_msg = await update.message.reply_text("📸 Анализирую изображение...")
    
    try:
        # Берем фото самого высокого качества
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        # Скачиваем фото правильно
        image_data = bytes(await file.download_as_bytearray())
        
        # Анализируем через Gemini Vision
        analysis = await analyze_image(image_data, caption)
        
        if analysis:
            await photo_msg.edit_text(
                f"📸 *Анализ изображения:*\n\n{analysis}",
                parse_mode="Markdown"
            )
        else:
            await photo_msg.edit_text(
                "❌ Не удалось проанализировать изображение.\n\n"
                "Попробуй:\n"
                "• Отправить фото с подписью что именно нужно найти\n"
                "• Убедись что фото чёткое и не слишком тёмное"
            )
            
    except Exception as e:
        logger.error(f"Photo processing error: {e}")
        await photo_msg.edit_text(f"❌ Ошибка при анализе фото: {e}")

# =============================================
#  MESSAGE PROCESSING
# =============================================
async def process_message(
    app: Application,
    chat_id: int,
    text: str,
    data: Dict[str, Any],
    reply_to_message_id: int = None
) -> None:
    """Обрабатывает сообщение и генерирует ответ через AI"""
    
    try:
        # Сохраняем сообщение пользователя
        add_message(data, "Пользователь", text)
        
        # Проверяем, нужно ли изучать тему
        if any(word in text.lower() for word in ["изучи", "расскажи", "объясни", "что такое", "кто такой"]):
            topic = text[:60]
            if topic not in data["topics"]:
                data["topics"].append(topic)
        
        # Строим контекст
        system_context = build_context(data)
        
        # Определяем тип запроса
        is_code = is_code_request(text)
        is_search = is_search_request(text)
        
        result = None
        ai_name = None
        
        if is_search:
            # Поиск в интернете
            search_results = await search_web(text)
            if search_results and search_results != "По вашему запросу ничего не найдено.":
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"🌐 *Результаты поиска:*\n\n{search_results[:3000]}",
                    parse_mode="Markdown"
                )
            
            # Получаем ответ AI с учетом результатов поиска
            search_context = system_context + f"\n\nРезультаты поиска:\n{search_results}"
            result, ai_name = await get_best_ai_response(
                f"На основе результатов поиска дай ответ: {text}",
                search_context
            )
        
        elif is_code:
            # Генерация кода
            result, ai_name = await generate_code_smart(text, system_context)
        
        else:
            # Обычный текстовый ответ
            result, ai_name = await get_best_ai_response(text, system_context)
        
        if not result:
            await app.bot.send_message(
                chat_id=chat_id,
                text="❌ Ни один AI провайдер не ответил. Попробуйте позже."
            )
            return
        
        # Сохраняем ответ
        add_message(data, "Агент", result[:400])
        
        # Проверяем, есть ли код в ответе
        code = extract_code_from_text(result)
        
        if code and len(code) > 100:
            # Сохраняем код в память
            data["last_code"] = code[:800]
            save_data(data)
            
            # Определяем расширение
            ext = detect_extension(text, code)
            filename = f"code_{datetime.now().strftime('%H%M%S')}.{ext}"
            
            # Сохраняем код во временный файл
            with open(filename, "w", encoding="utf-8") as f:
                f.write(code)
            
            # Получаем информацию о файле
            file_size = os.path.getsize(filename) / 1024  # в KB
            line_count = len(code.splitlines())
            
            # Отправляем файл
            with open(filename, "rb") as f:
                await app.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=filename,
                    caption=(
                        f"📁 `{filename}`\n"
                        f"📊 {file_size:.1f} KB • {line_count} строк\n"
                        f"🤖 {ai_name}"
                    )
                )
            
            # Удаляем временный файл
            os.remove(filename)
            
            # Отправляем объяснение, если оно есть
            explanation = re.sub(r'```.*?```', '', result, flags=re.DOTALL).strip()
            if explanation and len(explanation) > 50:
                await send_long_message(
                    app.bot,
                    chat_id,
                    f"✅ *Код готов!*\n\n{explanation}",
                )
        
        else:
            # Отправляем обычный текстовый ответ
            header = f"✅ *Готово!* (_{ai_name}_)\n\n"
            await send_long_message(
                app.bot,
                chat_id,
                header + result
            )
        
        # Сохраняем данные
        save_data(data)
        
    except Exception as e:
        logger.error(f"Process message error: {e}")
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Произошла ошибка: {e}"
            )
        except:
            pass

# =============================================
#  MAIN
# =============================================
# ---- ПОГОДА ----
# Словарь популярных городов СНГ для перевода
CITY_TRANSLATE = {
    "ташкент": "Tashkent", "москва": "Moscow", "питер": "Saint Petersburg",
    "санкт-петербург": "Saint Petersburg", "алматы": "Almaty", "алма-ата": "Almaty",
    "бишкек": "Bishkek", "астана": "Astana", "нур-султан": "Astana",
    "минск": "Minsk", "киев": "Kyiv", "баку": "Baku", "ереван": "Yerevan",
    "тбилиси": "Tbilisi", "душанбе": "Dushanbe", "ашхабад": "Ashgabat",
    "самарканд": "Samarkand", "бухара": "Bukhara", "андижан": "Andijan",
    "новосибирск": "Novosibirsk", "екатеринбург": "Yekaterinburg",
    "казань": "Kazan", "краснодар": "Krasnodar", "сочи": "Sochi",
}

async def get_weather(city: str = "Moscow") -> str:
    """Получает погоду через OpenWeatherMap"""
    try:
        # Переводим кириллицу на английский
        city_en = CITY_TRANSLATE.get(city.lower().strip(), city)
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city_en}&appid={WEATHER_KEY}&units=metric&lang=ru&cnt=8"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return f"❌ Город не найден: {city}"
        d = r.json()
        city_name = d["city"]["name"]
        country = d["city"]["country"]
        lines = [f"🌤 *Погода в {city_name}, {country}*\n"]
        seen_dates = []
        for item in d["list"]:
            dt = datetime.fromtimestamp(item["dt"])
            date_str = dt.strftime("%d.%m")
            time_str = dt.strftime("%H:%M")
            if date_str not in seen_dates:
                seen_dates.append(date_str)
                lines.append(f"\n📅 *{dt.strftime('%d.%m (%A)')}*")
            temp = round(item["main"]["temp"])
            feels = round(item["main"]["feels_like"])
            desc = item["weather"][0]["description"].capitalize()
            wind = item["wind"]["speed"]
            humidity = item["main"]["humidity"]
            emoji = "☀️" if "ясно" in desc.lower() else "🌧" if "дожд" in desc.lower() else "❄️" if "снег" in desc.lower() else "☁️"
            lines.append(f"  {time_str} {emoji} {temp}°C (ощущ. {feels}°C), {desc}, 💨{wind}м/с, 💧{humidity}%")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return "❌ Не удалось получить погоду. Попробуй позже."


async def morning_weather_job(app) -> None:
    """Утренняя рассылка погоды в 7:00"""
    while True:
        try:
            now = datetime.now()
            # Ждём до 7:00
            target = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait_secs = (target - now).total_seconds()
            logger.info(f"Morning weather job: sleeping {wait_secs:.0f}s until {target}")
            await asyncio.sleep(wait_secs)

            if OWNER_CHAT_ID:
                data = load_data()
                city = data.get("weather_city", "Moscow")
                weather = await get_weather(city)
                greeting = f"🌅 *Доброе утро, господин!*\n\n{weather}\n\n_Хорошего дня!_ 🎯"
                # AI добавляет краткий совет дня
                tip, _ = await get_best_ai_response(
                    "Дай один короткий мотивационный совет на сегодня — одно предложение.",
                    "Ты личный помощник. Отвечай кратко."
                )
                if tip:
                    greeting += f"\n\n💡 *Совет дня:* {tip}"
                await app.bot.send_message(OWNER_CHAT_ID, greeting, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Morning weather job error: {e}")
            await asyncio.sleep(3600)


# ---- ПЕРЕСКАЗ ССЫЛОК ----
async def fetch_url_content(url: str) -> str:
    """Скачивает и парсит содержимое страницы"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            # Убираем ненужное
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "ads"]):
                tag.decompose()
            # Берём основной текст
            main = soup.find("article") or soup.find("main") or soup.find("body")
            if main:
                text = main.get_text(separator=" ", strip=True)
            else:
                text = soup.get_text(separator=" ", strip=True)
            import re
            text = re.sub(r"\s+", " ", text).strip()
        except ImportError:
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", "", r.text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        
        return text[:8000] if text else "error:empty"
    except Exception as e:
        return f"error:{e}"


async def get_youtube_transcript(video_id: str) -> str:
    """Получает субтитры YouTube видео"""
    # Способ 1: youtube-transcript-api (реальные субтитры)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Пробуем русские субтитры, потом английские
        for lang in ['ru', 'en', 'a.ru', 'a.en']:
            try:
                transcript = transcript_list.find_transcript([lang])
                entries = transcript.fetch()
                text = " ".join(e['text'] for e in entries)
                return text[:6000]
            except:
                continue
    except Exception as e:
        logger.warning(f"Transcript API error: {e}")

    # Способ 2: YouTube Data API (название + описание)
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YOUTUBE_KEY}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        d = r.json()
        if d.get("items"):
            item = d["items"][0]
            title = item["snippet"]["title"]
            desc = item["snippet"]["description"][:3000]
            channel = item["snippet"]["channelTitle"]
            return f"Название: {title}\nКанал: {channel}\nОписание: {desc}"
    except Exception as e:
        logger.error(f"YouTube API error: {e}")

    return ""


async def summarize_url(url: str) -> str:
    """Пересказывает содержимое ссылки"""
    import re
    is_youtube = "youtube.com" in url or "youtu.be" in url
    content = ""

    if is_youtube:
        # Извлекаем video_id
        yt_match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
        if yt_match:
            video_id = yt_match.group(1)
            content = await get_youtube_transcript(video_id)
        if not content:
            content = await fetch_url_content(url)
    else:
        content = await fetch_url_content(url)

    if content.startswith("error:"):
        return f"❌ Не удалось открыть ссылку: {content[6:]}"
    if len(content) < 100:
        return "❌ Страница пустая или защищена от парсинга."

    source_type = "YouTube видео" if is_youtube else "страницу"
    prompt = (
        f"Я дам тебе содержимое {source_type}. Сделай подробный пересказ:\n"
        f"1. 📌 О чём материал (2-3 предложения)\n"
        f"2. 🔑 Главные идеи и факты (5-7 пунктов)\n"
        f"3. 💡 Выводы и что важно запомнить\n\n"
        f"Содержимое:\n{content[:5000]}"
    )
    result, ai_name = await get_best_ai_response(prompt, "Ты эксперт по анализу и пересказу контента. Отвечай на русском.")
    if result:
        return f"🔗 *Пересказ материала*\n_(AI: {ai_name})_\n\n{result}"
    return "❌ Не удалось создать пересказ."


# ---- АНАЛИЗ ФАЙЛОВ ----
async def analyze_document(file_bytes: bytes, filename: str, user_prompt: str = "") -> str:
    """Анализирует документ — PDF, TXT, DOCX и др."""
    import io
    text = ""
    fname_lower = filename.lower()

    try:
        if fname_lower.endswith(".txt") or fname_lower.endswith(".md"):
            text = file_bytes.decode("utf-8", errors="ignore")
        elif fname_lower.endswith(".pdf"):
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                pages_text = []
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        pages_text.append(t)
                text = "\n".join(pages_text)
                if not text.strip():
                    return "❌ PDF защищён или содержит только изображения — текст извлечь не удалось."
            except ImportError:
                return "❌ Библиотека pypdf не установлена."
            except Exception as e:
                return f"❌ Ошибка чтения PDF: {e}"
        elif fname_lower.endswith(".docx"):
            try:
                from docx import Document
                doc = Document(io.BytesIO(file_bytes))
                text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                # Fallback: читаем как zip и извлекаем XML
                try:
                    import zipfile, xml.etree.ElementTree as ET
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                        xml_content = z.read("word/document.xml")
                    root = ET.fromstring(xml_content)
                    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                    paragraphs = []
                    for para in root.iter(f"{ns}p"):
                        texts = [t.text for t in para.iter(f"{ns}t") if t.text]
                        if texts:
                            paragraphs.append("".join(texts))
                    text = "\n".join(paragraphs)
                except Exception as e2:
                    return f"❌ Не удалось прочитать DOCX: {e2}"
            except Exception as e:
                return f"❌ Ошибка чтения DOCX: {e}"
        elif fname_lower.endswith(".csv"):
            text = file_bytes.decode("utf-8", errors="ignore")[:5000]
        elif fname_lower.endswith((".xlsx", ".xls")):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
                rows = []
                for sheet in wb.sheetnames[:3]:  # макс 3 листа
                    ws = wb[sheet]
                    rows.append(f"=== Лист: {sheet} ===")
                    for row in ws.iter_rows(max_row=200, values_only=True):
                        row_text = " | ".join(str(c) if c is not None else "" for c in row)
                        if row_text.strip(" |"):
                            rows.append(row_text)
                text = "\n".join(rows)[:6000]
            except ImportError:
                return "❌ Библиотека openpyxl не установлена."
            except Exception as e:
                return f"❌ Ошибка чтения Excel: {e}"
        elif fname_lower.endswith(".pptx"):
            try:
                from pptx import Presentation
                prs = Presentation(io.BytesIO(file_bytes))
                slides_text = []
                for i, slide in enumerate(prs.slides, 1):
                    slide_content = []
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            slide_content.append(shape.text.strip())
                    if slide_content:
                        slides_text.append(f"[Слайд {i}] " + " | ".join(slide_content))
                text = "\n".join(slides_text)[:6000]
            except ImportError:
                return "❌ Библиотека python-pptx не установлена."
            except Exception as e:
                return f"❌ Ошибка чтения PPTX: {e}"
        elif fname_lower.endswith(".json"):
            try:
                import json as _json
                parsed = _json.loads(file_bytes.decode("utf-8", errors="ignore"))
                text = _json.dumps(parsed, ensure_ascii=False, indent=2)[:6000]
            except Exception as e:
                text = file_bytes.decode("utf-8", errors="ignore")[:5000]
        else:
            # Код и другие текстовые форматы
            text = file_bytes.decode("utf-8", errors="ignore")[:6000]
    except Exception as e:
        return f"❌ Ошибка чтения файла: {e}"

    if not text.strip():
        return "❌ Файл пустой или не удалось извлечь текст."

    action = user_prompt.lower() if user_prompt else ""

    if "конспект" in action or "краткое" in action:
        prompt = f"Сделай подробный конспект этого документа с заголовками и ключевыми пунктами:\n\n{text[:6000]}"
    elif "викторин" in action or "тест" in action or "вопрос" in action:
        prompt = f"Создай викторину из 10 вопросов с вариантами ответов (А/Б/В/Г) по этому материалу. В конце дай правильные ответы:\n\n{text[:6000]}"
    elif "перевод" in action or "перевести" in action:
        prompt = f"Переведи этот документ на русский язык:\n\n{text[:6000]}"
    else:
        prompt = (
            f"Проанализируй документ '{filename}':\n"
            f"1. 📌 О чём документ\n"
            f"2. 🔑 Ключевые моменты\n"
            f"3. 📊 Структура и содержание\n"
            f"4. 💡 Выводы\n\n"
            f"Документ:\n{text[:6000]}"
        )

    result, ai_name = await get_best_ai_response(prompt, "Ты эксперт по анализу документов. Отвечай на русском.")
    if result:
        return f"📄 *Анализ файла: {filename}*\n_(AI: {ai_name})_\n\n{result}"
    return "❌ Не удалось проанализировать файл."


# ---- ГЕНЕРАТОР ПРОМПТОВ ----
async def generate_prompt(description: str) -> str:
    """Генерирует оптимальный промпт по описанию"""
    prompt = (
        f"Пользователь хочет создать промпт для AI. Его описание:\n{description}\n\n"
        f"Создай 3 варианта промпта — от простого к сложному:\n"
        f"**Вариант 1 (простой):** ...\n"
        f"**Вариант 2 (средний):** ...\n"
        f"**Вариант 3 (продвинутый):** ...\n\n"
        f"Каждый промпт должен быть готов к использованию, на русском."
    )
    result, ai_name = await get_best_ai_response(prompt, "Ты эксперт по prompt engineering.")
    if result:
        return f"✍️ *Генератор промптов*\n_(AI: {ai_name})_\n\n{result}"
    return "❌ Не удалось создать промпт."


# ---- КОМАНДЫ ----
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /weather"""
    args = context.args
    city = " ".join(args) if args else None

    if not city:
        # Проверяем сохранённый город
        data = load_data()
        city = data.get("weather_city", "")

    if not city:
        await update.message.reply_text(
            "🌤 *Погода*\n\nНапиши название города:\nПример: Москва, Алматы, London",
            parse_mode="Markdown"
        )
        context.user_data["waiting_for"] = "weather_city"
        return

    msg = await update.message.reply_text(f"🌤 Получаю погоду для *{city}*...", parse_mode="Markdown")
    weather = await get_weather(city)

    # Сохраняем город
    data = load_data()
    data["weather_city"] = city
    save_data(data)

    await msg.edit_text(weather, parse_mode="Markdown")


async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /summarize или кнопка Пересказ ссылки"""
    await update.message.reply_text(
        "🔗 *Пересказ ссылки*\n\nОтправь ссылку на:\n"
        "• YouTube видео\n• Статью или сайт\n• Новость\n\nПросто вставь URL:",
        parse_mode="Markdown"
    )
    context.user_data["waiting_for"] = "summarize_url"


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик файлов — анализ документов"""
    doc = update.message.document
    if not doc:
        return

    allowed = [".txt", ".pdf", ".docx", ".md", ".csv", ".xlsx", ".xls", ".pptx", ".json", ".py", ".js", ".html", ".xml"]
    fname = doc.file_name or "document"
    ext = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

    if ext not in allowed:
        await update.message.reply_text(
            f"❌ Формат {ext} не поддерживается.\n"
            f"Поддерживаю: PDF, DOCX, XLSX, PPTX, TXT, CSV, JSON, MD, PY, JS, HTML, XML"
        )
        return

    if doc.file_size > 10 * 1024 * 1024:  # 10MB
        await update.message.reply_text("❌ Файл слишком большой (макс. 10MB)")
        return

    msg = await update.message.reply_text(f"📄 Читаю *{fname}*...", parse_mode="Markdown")

    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        # Берём caption как подсказку что делать
        user_prompt = update.message.caption or ""

        result = await analyze_document(bytes(file_bytes), fname, user_prompt)
        await msg.delete()
        await send_long_message(context.application.bot, update.effective_chat.id, result, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Document handler error: {e}")
        await msg.edit_text(f"❌ Ошибка: {e}")



async def post_init(application: Application) -> None:
    """Действия после инициализации бота"""
    # Устанавливаем команды меню
    commands = [
        BotCommand("start", "🚀 Главное меню"),
        BotCommand("restart", "🔄 Перезапустить бота"),
        BotCommand("status", "📡 Статус AI провайдеров"),
        BotCommand("memory", "🧠 Память и история"),
        BotCommand("clear", "🗑 Очистить чат"),
        BotCommand("new", "💬 Новый чат"),
        BotCommand("chats", "📂 Список чатов"),
        BotCommand("search", "🌐 Поиск в интернете"),
        BotCommand("reminders", "⏰ Напоминания"),
        BotCommand("help", "❓ Помощь"),
        BotCommand("weather", "🌤 Погода"),
        BotCommand("summarize", "🔗 Пересказ ссылки"),
    ]
    
    await application.bot.set_my_commands(commands)
    
    # Запускаем фоновый цикл проверки напоминаний
    asyncio.create_task(reminder_check_loop(application))
    asyncio.create_task(morning_weather_job(application))

    logger.info("Бот успешно запущен!")

def main() -> None:
    """Главная функция запуска бота"""
    
    # Создаем приложение
    application = Application.builder()\
        .token(TELEGRAM_TOKEN)\
        .post_init(post_init)\
        .build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("memory", memory_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("new", new_chat_command))
    application.add_handler(CommandHandler("chats", chats_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("reminders", reminders_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Регистрируем обработчик инлайн кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Регистрируем обработчики сообщений
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("summarize", summarize_command))
    
    # Запускаем бота
    logger.info("Запуск бота...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
        close_loop=False
    )

if __name__ == "__main__":
    main()
