import json
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

# ══════════════════════════════════════════
#  КЛЮЧИ API
# ══════════════════════════════════════════
TELEGRAM_TOKEN  = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GROQ_API_KEY    = "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"
GEMINI_API_KEY  = "AIzaSyD21rIGQxhzh6HXvb05Tkc5SYLBsFVn5II"
DEEPSEEK_KEY    = "sk-5c112016a71c444e88ea825e3f8c7d4f"
COHERE_KEY      = "UwiOG7P74hXPKzrSK4rk2P2xaRxw2Bc9R3PhXmT2"
OPENROUTER_KEY  = "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"
SERPER_KEY      = "2def7b1526652c4af691804cd8ed41231666d0be"

DATA_FILE      = "data.json"
REMINDERS_FILE = "reminders.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
#  ШАБЛОНЫ
# ══════════════════════════════════════════
TEMPLATES = {
    "🌐 Сайт HTML":      "Напиши полный HTML файл с красивым дизайном, CSS и JS внутри одного файла. Сделай: ",
    "🐍 Python код":     "Напиши полный рабочий Python код без сокращений. Задача: ",
    "🤖 Telegram бот":   "Напиши полный код Telegram бота на Python. Бот должен: ",
    "🎮 Игра":           "Напиши полную игру на Python или HTML/JS. Игра: ",
    "📱 Приложение":     "Напиши полное приложение, весь код целиком. Приложение: ",
    "🗄️ База данных":   "Напиши полный Python код с SQLite базой данных. Функционал: ",
    "🎯 C++ код":        "Напиши полный рабочий C++ код без сокращений. Задача: ",
    "⚡ JavaScript":     "Напиши полный JavaScript код в одном файле. Задача: ",
    "📚 Объяснить":      "Объясни простым языком как другу, с примерами и аналогиями: ",
    "🔍 Найти в сети":   "Найди актуальную информацию в интернете про: ",
}

# ══════════════════════════════════════════
#  КЛАВИАТУРА
# ══════════════════════════════════════════
def main_keyboard():
    keyboard = [
        [KeyboardButton("💬 Новый чат"),    KeyboardButton("📂 Мои чаты")],
        [KeyboardButton("📋 Шаблоны"),      KeyboardButton("🔍 Поиск в сети")],
        [KeyboardButton("⏰ Напоминания"),   KeyboardButton("🧠 Память")],
        [KeyboardButton("📡 Статус AI"),    KeyboardButton("❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

def templates_keyboard():
    keyboard = []
    items = list(TEMPLATES.keys())
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(items[i], callback_data=f"tmpl_{i}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(items[i+1], callback_data=f"tmpl_{i+1}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# ══════════════════════════════════════════
#  ДАННЫЕ
# ══════════════════════════════════════════
def load_data():
    if Path(DATA_FILE).exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "current_chat": "default",
        "chats": {"default": {"name": "Основной чат", "history": [], "created": datetime.now().strftime("%d.%m.%Y")}},
        "learned_topics": []
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_reminders():
    if Path(REMINDERS_FILE).exists():
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_reminders(r):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)

def get_current_history(data):
    return data["chats"][data["current_chat"]]["history"]

def add_message(data, role, text):
    h = get_current_history(data)
    h.append({"role": role, "text": text[:500], "time": datetime.now().strftime("%d.%m %H:%M")})
    if len(h) > 50:
        data["chats"][data["current_chat"]]["history"] = h[-50:]

def build_context(data):
    history = get_current_history(data)[-8:]
    h_text = "\n".join([f"{m['role']}: {m['text']}" for m in history])
    topics = ", ".join(data["learned_topics"][-10:]) or "пока ничего"
    chat_name = data["chats"][data["current_chat"]]["name"]
    return f"""Ты профессиональный AI-агент и опытный разработчик. Всегда отвечай на русском.
Текущий чат: {chat_name}
Изученные темы: {topics}
История: {h_text}
ПРАВИЛА: Код пиши ПОЛНОСТЬЮ без сокращений и заглушек. Объясняй просто как другу."""

def extract_code(text):
    all_codes = []
    for p in [r'```\w*\n(.*?)```', r'```(.*?)```']:
        all_codes.extend(re.findall(p, text, re.DOTALL))
    return max(all_codes, key=len).strip() if all_codes else None

def detect_ext(prompt, code):
    p = prompt.lower()
    if 'html' in p or 'сайт' in p or 'веб' in p: return 'html'
    if 'css' in p: return 'css'
    if 'javascript' in p or ' js ' in p: return 'js'
    if 'typescript' in p: return 'ts'
    if 'c++' in p or 'cpp' in p: return 'cpp'
    if 'c#' in p or 'шарп' in p: return 'cs'
    if 'kotlin' in p: return 'kt'
    if 'swift' in p: return 'swift'
    if 'rust' in p: return 'rs'
    if 'golang' in p or ' go ' in p: return 'go'
    if 'php' in p: return 'php'
    if 'ruby' in p: return 'rb'
    if 'bash' in p or 'shell' in p: return 'sh'
    if 'sql' in p: return 'sql'
    if 'dart' in p or 'flutter' in p: return 'dart'
    if 'java ' in p: return 'java'
    if code:
        if '#include' in code or 'cout' in code: return 'cpp'
        if 'using System' in code: return 'cs'
        if 'console.log' in code: return 'js'
        if '<html' in code: return 'html'
    return 'py'

def is_code_task(text):
    return any(k in text.lower() for k in [
        "создай","напиши","сделай","код","приложение","скрипт",
        "программу","бот","сайт","функцию","калькулятор","игру","база данных"
    ])

def needs_search(text):
    return any(k in text.lower() for k in [
        "найди","поищи","что сейчас","новости","актуально",
        "курс","погода","цена","когда вышел","кто такой"
    ])

# ══════════════════════════════════════════
#  AI ПРОВАЙДЕРЫ
# ══════════════════════════════════════════
async def ask_groq(prompt, context):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "system", "content": context}, {"role": "user", "content": prompt}],
            "max_tokens": 8000, "temperature": 0.3
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=payload, headers=headers)
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None

async def ask_gemini(prompt, context):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": f"{context}\n\nПользователь: {prompt}\n\nПиши ПОЛНЫЙ код!"}]}],
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3}
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=payload)
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini: {e}")
        return None

async def ask_openrouter(prompt, context):
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "system", "content": context}, {"role": "user", "content": prompt}],
            "max_tokens": 8000
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=payload, headers=headers)
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None

async def ask_cohere(prompt, context):
    try:
        url = "https://api.cohere.ai/v1/chat"
        headers = {"Authorization": f"Bearer {COHERE_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "command-r-plus",
            "message": prompt,
            "preamble": context,
            "max_tokens": 4000
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=payload, headers=headers)
            return r.json()["text"]
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

async def ask_deepseek(prompt, context):
    try:
        url = "https://api.deepseek.com/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": context}, {"role": "user", "content": prompt}],
            "max_tokens": 8000
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=payload, headers=headers)
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"DeepSeek: {e}")
        return None

async def smart_ai(prompt, context, prefer_code=False):
    """Умный выбор AI — пробует по очереди пока кто-то не ответит"""
    if prefer_code:
        # Для кода: OpenRouter (DeepSeek) → Gemini → Groq → Cohere
        providers = [
            ("OpenRouter/DeepSeek", ask_openrouter),
            ("Gemini", ask_gemini),
            ("Groq", ask_groq),
            ("Cohere", ask_cohere),
        ]
    else:
        # Для текста: Groq → OpenRouter → Gemini → Cohere
        providers = [
            ("Groq", ask_groq),
            ("OpenRouter", ask_openrouter),
            ("Gemini", ask_gemini),
            ("Cohere", ask_cohere),
        ]
    for name, func in providers:
        logger.info(f"Trying {name}...")
        result = await func(prompt, context)
        if result:
            logger.info(f"Success: {name}")
            return result, name
    return None, None

async def ping_all_providers():
    """Проверяет все AI провайдеры"""
    test_prompt = "Скажи 'ок' одним словом"
    test_context = "Ты помощник"
    results = {}
    providers = [
        ("🟢 Groq", ask_groq),
        ("💎 Gemini", ask_gemini),
        ("🔷 OpenRouter", ask_openrouter),
        ("🟡 Cohere", ask_cohere),
        ("🔵 DeepSeek", ask_deepseek),
    ]
    tasks = [(name, func(test_prompt, test_context)) for name, func in providers]
    for name, coro in tasks:
        try:
            result = await asyncio.wait_for(coro, timeout=15)
            results[name] = "✅ Работает" if result else "❌ Не отвечает"
        except asyncio.TimeoutError:
            results[name] = "⏱ Таймаут"
        except Exception:
            results[name] = "❌ Ошибка"
    return results

# ══════════════════════════════════════════
#  ГОЛОС И ФОТО
# ══════════════════════════════════════════
async def transcribe_voice(file_bytes):
    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        files = {"file": ("audio.ogg", file_bytes, "audio/ogg"), "model": (None, "whisper-large-v3")}
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, headers=headers, files=files)
            return r.json().get("text", "")
    except Exception as e:
        logger.error(f"Whisper: {e}")
        return ""

async def analyze_image(image_bytes, prompt):
    try:
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
            {"text": prompt or "Опиши подробно что видишь на изображении. Отвечай на русском."}
        ]}]}
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json=payload)
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Vision: {e}")
        return None

# ══════════════════════════════════════════
#  ПОИСК
# ══════════════════════════════════════════
async def search_web(query):
    try:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}
        payload = {"q": query, "gl": "ru", "hl": "ru", "num": 5}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, json=payload, headers=headers)
            data = r.json()
        results = []
        if "answerBox" in data:
            ans = data["answerBox"].get("answer") or data["answerBox"].get("snippet", "")
            if ans: results.append(f"📌 {ans}")
        for item in data.get("organic", [])[:4]:
            results.append(f"• *{item.get('title','')}*\n{item.get('snippet','')}")
        return "\n\n".join(results) if results else "Ничего не найдено"
    except Exception as e:
        logger.error(f"Search: {e}")
        return "Ошибка поиска"

# ══════════════════════════════════════════
#  НАПОМИНАНИЯ
# ══════════════════════════════════════════
def parse_reminder_time(text):
    now = datetime.now()
    patterns = [
        (r'через (\d+) минут', lambda m: now + timedelta(minutes=int(m.group(1)))),
        (r'через (\d+) час',   lambda m: now + timedelta(hours=int(m.group(1)))),
        (r'через (\d+) день',  lambda m: now + timedelta(days=int(m.group(1)))),
        (r'завтра в (\d+):(\d+)', lambda m: (now + timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0)),
        (r'в (\d+):(\d+)',     lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0)),
    ]
    for pattern, fn in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return fn(match), re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
    return None, text

async def check_reminders(app):
    while True:
        try:
            reminders = load_reminders()
            now = datetime.now()
            remaining = []
            for r in reminders:
                if now >= datetime.fromisoformat(r["time"]):
                    await app.bot.send_message(r["chat_id"], f"⏰ *Напоминание!*\n\n{r['text']}", parse_mode="Markdown")
                else:
                    remaining.append(r)
            if len(remaining) != len(reminders):
                save_reminders(remaining)
        except Exception as e:
            logger.error(f"Reminder check: {e}")
        await asyncio.sleep(60)

# ══════════════════════════════════════════
#  ФОНОВАЯ ОБРАБОТКА
# ══════════════════════════════════════════
async def process_background(app, chat_id, text, data, image_bytes=None):
    try:
        context = build_context(data)

        if image_bytes:
            await app.bot.send_message(chat_id, "🔍 Анализирую изображение...")
            result = await analyze_image(image_bytes, text)
            if result:
                await app.bot.send_message(chat_id, f"🖼 *Анализ:*\n\n{result}", parse_mode="Markdown")
            else:
                await app.bot.send_message(chat_id, "❌ Не удалось проанализировать")
            return

        await app.bot.send_message(chat_id, "⚙️ Работаю в фоне... Занимайся своими делами!")

        result, used_ai = None, None

        if needs_search(text):
            await app.bot.send_message(chat_id, "🌐 Ищу в интернете...")
            search_results = await search_web(text)
            search_ctx = f"{context}\n\nРезультаты поиска:\n{search_results}"
            result, used_ai = await smart_ai(f"Ответь на вопрос на основе поиска: {text}", search_ctx)
            if result:
                await app.bot.send_message(chat_id, f"🌐 *Найдено:*\n\n{search_results[:2000]}", parse_mode="Markdown")

        elif is_code_task(text):
            await app.bot.send_message(chat_id, "💻 Пишу полный код...")
            result, used_ai = await smart_ai(text, context, prefer_code=True)

        else:
            result, used_ai = await smart_ai(text, context)

        if not result:
            await app.bot.send_message(chat_id, "❌ Все AI не ответили. Попробуй позже.")
            return

        add_message(data, "Пользователь", text)
        add_message(data, "Агент", result[:400])
        if any(w in text.lower() for w in ["изучи", "расскажи", "объясни", "что такое"]):
            t = text[:60]
            if t not in data["learned_topics"]:
                data["learned_topics"].append(t)
        save_data(data)

        # Отправка кода файлом
        if is_code_task(text):
            code = extract_code(result)
            if code and len(code) > 100:
                ext = detect_ext(text, code)
                fname = f"code.{ext}"
                explanation = re.sub(r'```.*?```', '', result, flags=re.DOTALL).strip()
                if explanation and len(explanation) > 20:
                    for chunk in [explanation[i:i+4000] for i in range(0, len(explanation), 4000)]:
                        await app.bot.send_message(chat_id, f"✅ Готово! _{used_ai}_\n\n{chunk}", parse_mode="Markdown")
                with open(fname, 'w', encoding='utf-8') as f:
                    f.write(code)
                size_kb = os.path.getsize(fname) / 1024
                with open(fname, 'rb') as f:
                    await app.bot.send_document(chat_id, document=f, filename=fname,
                        caption=f"📁 `{fname}` • {size_kb:.1f} KB\n🤖 {used_ai}")
                os.remove(fname)
                return

        full = f"✅ Готово! _{used_ai}_\n\n{result}"
        if len(full) > 4096:
            await app.bot.send_message(chat_id, f"✅ Готово! _{used_ai}_ Отправляю частями:", parse_mode="Markdown")
            for i, chunk in enumerate([result[i:i+4000] for i in range(0, len(result), 4000)], 1):
                await app.bot.send_message(chat_id, f"Часть {i}:\n{chunk}")
        else:
            await app.bot.send_message(chat_id, full, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"process_background: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {str(e)}")

# ══════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.message.reply_text(
        f"👋 *Привет! Я твой персональный AI-агент*\n\n"
        f"📊 Статус:\n"
        f"├ 💬 Чат: {data['chats'][data['current_chat']]['name']}\n"
        f"├ 📁 Чатов: {len(data['chats'])}\n"
        f"└ 📚 Тем изучено: {len(data['learned_topics'])}\n\n"
        f"🤖 5 AI провайдеров:\n"
        f"├ Groq • Gemini • OpenRouter\n"
        f"└ Cohere • DeepSeek\n\n"
        f"🚀 Умею:\n"
        f"├ 💻 Код на 15+ языках → файлом\n"
        f"├ 🎤 Голосовые сообщения\n"
        f"├ 📸 Анализ фото\n"
        f"├ 🌐 Поиск в интернете\n"
        f"└ ⏰ Напоминания\n\n"
        f"👇 Используй кнопки!",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🔄 *Перезапущен!* Готов к работе 👇", parse_mode="Markdown", reply_markup=main_keyboard())

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 Проверяю все AI провайдеры... Подожди 15 сек")
    results = await ping_all_providers()
    text = "📡 *Статус AI провайдеров:*\n\n"
    for name, status in results.items():
        text += f"{name}: {status}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def new_chat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Введи название нового чата:")
    context.user_data["waiting_chat_name"] = True

async def list_chats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    current = data["current_chat"]
    keyboard = []
    for key, chat in data["chats"].items():
        mark = "✅ " if key == current else "💬 "
        keyboard.append([InlineKeyboardButton(f"{mark}{chat['name']} ({len(chat['history'])} сообщ.)", callback_data=f"switch_{key}")])
    keyboard.append([InlineKeyboardButton("➕ Новый", callback_data="new_chat_inline"), InlineKeyboardButton("🗑 Удалить", callback_data="show_delete")])
    await update.message.reply_text("💬 *Твои чаты:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def templates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 *Выбери шаблон:*", parse_mode="Markdown", reply_markup=templates_keyboard())

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 Что ищем?")
    context.user_data["waiting_search"] = True

async def reminders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = load_reminders()
    chat_id = update.effective_chat.id
    my = [r for r in reminders if r["chat_id"] == chat_id]
    keyboard = [[InlineKeyboardButton("➕ Добавить", callback_data="add_reminder")]]
    text = "⏰ *Напоминания:*\n\n"
    if my:
        for i, r in enumerate(my[:5]):
            t = datetime.fromisoformat(r["time"]).strftime("%d.%m в %H:%M")
            text += f"• {r['text']} — *{t}*\n"
            keyboard.append([InlineKeyboardButton(f"🗑 Удалить: {r['text'][:25]}", callback_data=f"del_rem_{i}")])
    else:
        text += "Нет активных\n\nПримеры:\n• _напомни через 30 минут позвонить_\n• _напомни в 15:30 встреча_\n• _напомни завтра в 10:00 купить_"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    topics = "\n".join([f"• {t}" for t in data["learned_topics"][-15:]]) or "Пока ничего"
    current = data["chats"][data["current_chat"]]["name"]
    await update.message.reply_text(
        f"🧠 *Память:*\n\n"
        f"├ 💬 Чат: {current}\n"
        f"├ 📨 Сообщений: {len(get_current_history(data))}\n"
        f"└ 📁 Чатов: {len(data['chats'])}\n\n"
        f"📚 *Изученные темы:*\n{topics}",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    name = data["chats"][data["current_chat"]]["name"]
    data["chats"][data["current_chat"]]["history"] = []
    save_data(data)
    await update.message.reply_text(f"🗑 Чат «{name}» очищен!", reply_markup=main_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Как пользоваться:*\n\n"
        "🎤 Отправь голосовое — распознаю и отвечу\n"
        "📸 Отправь фото — опишу что вижу\n"
        "🌐 Кнопка поиск или напиши 'найди...'\n"
        "⏰ Напиши 'напомни через 1 час...'\n"
        "💻 Напиши 'создай приложение...'\n"
        "📡 Кнопка Статус AI — проверить провайдеры\n\n"
        "⌨️ *Команды:*\n"
        "/start — главное меню\n"
        "/restart — перезапустить\n"
        "/status — статус всех AI\n"
        "/new — новый чат\n"
        "/chats — список чатов\n"
        "/memory — память\n"
        "/clear — очистить чат",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )

# ══════════════════════════════════════════
#  МЕДИА
# ══════════════════════════════════════════
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("🎤 Распознаю голос...")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        async with httpx.AsyncClient() as c:
            r = await c.get(file.file_path)
        text = await transcribe_voice(r.content)
        if text:
            await update.message.reply_text(f"🎤 Ты сказал:\n_{text}_", parse_mode="Markdown")
            data = load_data()
            asyncio.create_task(process_background(context.application, chat_id, text, data))
        else:
            await update.message.reply_text("❌ Не удалось распознать")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""
    await update.message.reply_text("📸 Анализирую...")
    try:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        async with httpx.AsyncClient() as c:
            r = await c.get(file.file_path)
        data = load_data()
        asyncio.create_task(process_background(context.application, chat_id, caption, data, image_bytes=r.content))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ══════════════════════════════════════════
#  КНОПКИ
# ══════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    chat_id = update.effective_chat.id

    if query.data.startswith("switch_"):
        key = query.data[7:]
        if key in data["chats"]:
            data["current_chat"] = key
            save_data(data)
            await query.edit_message_text(f"✅ Чат: *{data['chats'][key]['name']}*", parse_mode="Markdown")

    elif query.data == "new_chat_inline":
        await query.edit_message_text("✏️ Напиши название нового чата:")
        context.user_data["waiting_chat_name"] = True

    elif query.data == "show_delete":
        keyboard = [[InlineKeyboardButton(f"🗑 {c['name']}", callback_data=f"delete_{k}")]
                    for k, c in data["chats"].items() if k != "default"]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_chats")])
        if len(keyboard) == 1:
            await query.edit_message_text("❌ Нет чатов для удаления")
        else:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    elif query.data == "back_chats":
        current = data["current_chat"]
        keyboard = [[InlineKeyboardButton(("✅ " if k == current else "💬 ") + f"{c['name']} ({len(c['history'])} сообщ.)", callback_data=f"switch_{k}")]
                    for k, c in data["chats"].items()]
        keyboard.append([InlineKeyboardButton("➕ Новый", callback_data="new_chat_inline"), InlineKeyboardButton("🗑 Удалить", callback_data="show_delete")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("delete_"):
        key = query.data[7:]
        if key in data["chats"]:
            name = data["chats"][key]["name"]
            del data["chats"][key]
            if data["current_chat"] == key:
                data["current_chat"] = list(data["chats"].keys())[0]
            save_data(data)
            await query.edit_message_text(f"🗑 Чат *{name}* удалён!", parse_mode="Markdown")

    elif query.data.startswith("tmpl_"):
        idx = int(query.data[5:])
        keys = list(TEMPLATES.keys())
        if idx < len(keys):
            k = keys[idx]
            await query.edit_message_text(f"📋 *{k}*\n\nСкопируй и допиши:\n\n`{TEMPLATES[k]}`", parse_mode="Markdown")

    elif query.data == "add_reminder":
        await query.edit_message_text(
            "⏰ Напиши напоминание:\n\n"
            "_напомни через 30 минут позвонить_\n"
            "_напомни в 15:30 встреча_\n"
            "_напомни завтра в 10:00 купить_",
            parse_mode="Markdown"
        )
        context.user_data["waiting_reminder"] = True

    elif query.data.startswith("del_rem_"):
        idx = int(query.data[8:])
        reminders = load_reminders()
        my = [r for r in reminders if r["chat_id"] == chat_id]
        if idx < len(my):
            reminders.remove(my[idx])
            save_reminders(reminders)
            await query.edit_message_text("🗑 Напоминание удалено!")

# ══════════════════════════════════════════
#  ОБРАБОТКА ТЕКСТА
# ══════════════════════════════════════════
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    actions = {
        "💬 Новый чат":   new_chat_cmd,
        "📂 Мои чаты":    list_chats_cmd,
        "📋 Шаблоны":     templates_cmd,
        "🔍 Поиск в сети": search_cmd,
        "⏰ Напоминания":  reminders_cmd,
        "🧠 Память":       memory_cmd,
        "📡 Статус AI":    status_cmd,
        "🗑 Очистить чат": clear_cmd,
        "❓ Помощь":       help_cmd,
    }
    if text in actions:
        await actions[text](update, context)
        return

    if context.user_data.get("waiting_chat_name"):
        context.user_data["waiting_chat_name"] = False
        data = load_data()
        key = f"chat_{int(datetime.now().timestamp())}"
        data["chats"][key] = {"name": text, "history": [], "created": datetime.now().strftime("%d.%m %H:%M")}
        data["current_chat"] = key
        save_data(data)
        await update.message.reply_text(f"✅ Новый чат: *{text}*", parse_mode="Markdown", reply_markup=main_keyboard())
        return

    if context.user_data.get("waiting_search"):
        context.user_data["waiting_search"] = False
        await update.message.reply_text("🌐 Ищу...")
        results = await search_web(text)
        data = load_data()
        ctx = f"{build_context(data)}\n\nПоиск:\n{results}"
        answer, ai = await smart_ai(f"Ответь на основе поиска: {text}", ctx)
        await update.message.reply_text(f"🌐 *Найдено:*\n\n{results[:2000]}", parse_mode="Markdown")
        if answer:
            await update.message.reply_text(f"💡 *Итог ({ai}):*\n\n{answer[:2000]}", parse_mode="Markdown")
        return

    if context.user_data.get("waiting_reminder"):
        context.user_data["waiting_reminder"] = False
        remind_time, remind_text = parse_reminder_time(text)
        if remind_time:
            reminders = load_reminders()
            reminders.append({"chat_id": chat_id, "text": remind_text, "time": remind_time.isoformat()})
            save_reminders(reminders)
            await update.message.reply_text(
                f"⏰ Поставил!\n\n📝 {remind_text}\n🕐 {remind_time.strftime('%d.%m в %H:%M')}",
                reply_markup=main_keyboard()
            )
        else:
            await update.message.reply_text("❌ Не понял время. Попробуй: 'напомни через 1 час сделать что-то'")
        return

    if any(w in text.lower() for w in ["напомни", "поставь напоминание"]):
        remind_time, remind_text = parse_reminder_time(text)
        if remind_time:
            reminders = load_reminders()
            reminders.append({"chat_id": chat_id, "text": remind_text, "time": remind_time.isoformat()})
            save_reminders(reminders)
            await update.message.reply_text(
                f"⏰ Напоминание поставлено!\n\n📝 {remind_text}\n🕐 {remind_time.strftime('%d.%m в %H:%M')}",
                reply_markup=main_keyboard()
            )
            return

    data = load_data()
    asyncio.create_task(process_background(context.application, chat_id, text, data))

# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════
async def post_init(app):
    asyncio.create_task(check_reminders(app))
    await app.bot.set_my_commands([
        ("start",     "🚀 Запустить бота / Главное меню"),
        ("restart",   "🔄 Перезапустить бота"),
        ("status",    "📡 Статус всех AI провайдеров"),
        ("new",       "💬 Создать новый чат"),
        ("chats",     "📂 Список всех чатов"),
        ("search",    "🌐 Поиск в интернете"),
        ("reminders", "⏰ Мои напоминания"),
        ("memory",    "🧠 Что бот помнит обо мне"),
        ("clear",     "🗑 Очистить текущий чат"),
        ("help",      "❓ Помощь и инструкции"),
    ])

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("restart",   restart_cmd))
    app.add_handler(CommandHandler("status",    status_cmd))
    app.add_handler(CommandHandler("new",       new_chat_cmd))
    app.add_handler(CommandHandler("chats",     list_chats_cmd))
    app.add_handler(CommandHandler("search",    search_cmd))
    app.add_handler(CommandHandler("reminders", reminders_cmd))
    app.add_handler(CommandHandler("memory",    memory_cmd))
    app.add_handler(CommandHandler("clear",     clear_cmd))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
