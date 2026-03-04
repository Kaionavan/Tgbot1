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

TELEGRAM_TOKEN = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GROQ_API_KEY = "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"
GEMINI_API_KEY = "AIzaSyD21rIGQxhzh6HXvb05Tkc5SYLBsFVn5II"
SERPER_API_KEY = "2def7b1526652c4af691804cd8ed41231666d0be"
DATA_FILE = "data.json"
REMINDERS_FILE = "reminders.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
#  ШАБЛОНЫ
# ══════════════════════════════════════════
TEMPLATES = {
    "🌐 Сайт": "Напиши полный HTML файл с красивым дизайном, CSS и JavaScript внутри одного файла. Сделай: ",
    "🐍 Python": "Напиши полный рабочий Python код без сокращений. Сделай: ",
    "🤖 Telegram бот": "Напиши полный код Telegram бота на Python. Бот должен: ",
    "🎮 Игра": "Напиши полную игру на Python или HTML/JS. Игра: ",
    "📱 Приложение": "Напиши полное приложение, весь код целиком. Приложение: ",
    "🗄️ База данных": "Напиши полный Python код с SQLite. Функционал: ",
    "🎯 C++ код": "Напиши полный рабочий C++ код. Задача: ",
    "⚡ JavaScript": "Напиши полный JavaScript код. Задача: ",
    "📚 Объяснить": "Объясни простым языком с примерами: ",
    "🔍 Найти в сети": "Найди актуальную информацию в интернете про: ",
}

# ══════════════════════════════════════════
#  КЛАВИАТУРА
# ══════════════════════════════════════════
def main_keyboard():
    keyboard = [
        [KeyboardButton("💬 Новый чат"), KeyboardButton("📂 Мои чаты")],
        [KeyboardButton("📋 Шаблоны"), KeyboardButton("🔍 Поиск в сети")],
        [KeyboardButton("⏰ Напоминания"), KeyboardButton("🧠 Память")],
        [KeyboardButton("🗑 Очистить чат"), KeyboardButton("❓ Помощь")],
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
        "chats": {
            "default": {"name": "Основной чат", "history": [], "created": datetime.now().strftime("%d.%m.%Y")}
        },
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

def save_reminders(reminders):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)

def get_current_history(data):
    return data["chats"][data["current_chat"]]["history"]

def add_message(data, role, text):
    history = get_current_history(data)
    history.append({"role": role, "text": text[:500], "time": datetime.now().strftime("%d.%m %H:%M")})
    if len(history) > 50:
        data["chats"][data["current_chat"]]["history"] = history[-50:]

def build_context(data):
    history = get_current_history(data)[-8:]
    history_text = "\n".join([f"{m['role']}: {m['text']}" for m in history])
    topics = ", ".join(data["learned_topics"][-10:]) or "пока ничего"
    chat_name = data["chats"][data["current_chat"]]["name"]
    return f"""Ты профессиональный AI-агент и опытный разработчик. Отвечай на русском.
Текущий чат: {chat_name}
Изученные темы: {topics}
История: {history_text}
ПРАВИЛА: Когда пишешь код — пиши ПОЛНЫЙ код целиком без сокращений и заглушек. Объясняй просто как другу."""

def extract_code(text):
    all_codes = []
    for pattern in [r'```\w*\n(.*?)```', r'```(.*?)```']:
        matches = re.findall(pattern, text, re.DOTALL)
        all_codes.extend(matches)
    if all_codes:
        return max(all_codes, key=len).strip()
    return None

def detect_file_type(prompt, code):
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
    if 'java ' in p or ' java' in p: return 'java'
    if code:
        if '#include' in code or 'cout' in code: return 'cpp'
        if 'using System' in code: return 'cs'
        if 'public class' in code and 'System.out' in code: return 'java'
        if 'fun main' in code: return 'kt'
        if 'console.log' in code or 'const ' in code: return 'js'
        if '<html' in code or '<!DOCTYPE' in code: return 'html'
    return 'py'

def is_code_task(text):
    keywords = ["создай", "напиши", "сделай", "код", "приложение", "скрипт",
                "программу", "бот", "сайт", "функцию", "калькулятор", "игру", "база данных"]
    return any(k in text.lower() for k in keywords)

def needs_search(text):
    keywords = ["найди", "поищи", "что сейчас", "последние новости", "актуально",
                "курс", "погода", "цена", "когда", "где", "кто такой", "что такое"]
    return any(k in text.lower() for k in keywords)

# ══════════════════════════════════════════
#  AI ФУНКЦИИ
# ══════════════════════════════════════════
async def ask_gemini(prompt, context):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": f"{context}\n\nПользователь: {prompt}\n\nВАЖНО: Пиши ПОЛНЫЙ рабочий код целиком!"}]}],
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3}
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return None

async def ask_groq_text(prompt, context):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "system", "content": context}, {"role": "user", "content": prompt}],
            "max_tokens": 8000, "temperature": 0.3
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, json=payload, headers=headers)
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

async def transcribe_voice(file_bytes: bytes) -> str:
    """Распознаёт голос через Groq Whisper"""
    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        files = {"file": ("audio.ogg", file_bytes, "audio/ogg"), "model": (None, "whisper-large-v3")}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, files=files)
            return r.json().get("text", "")
    except Exception as e:
        logger.error(f"Whisper error: {e}")
        return ""

async def analyze_image(image_bytes: bytes, prompt: str) -> str:
    """Анализирует изображение через Gemini Vision"""
    try:
        import base64
        image_b64 = base64.b64encode(image_bytes).decode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                    {"text": prompt or "Опиши подробно что видишь на этом изображении. Отвечай на русском."}
                ]
            }]
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return None

async def search_web(query: str) -> str:
    """Поиск в интернете через Serper"""
    try:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
        payload = {"q": query, "gl": "ru", "hl": "ru", "num": 5}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload, headers=headers)
            data = r.json()
        results = []
        if "answerBox" in data:
            results.append(f"📌 {data['answerBox'].get('answer', data['answerBox'].get('snippet', ''))}")
        for item in data.get("organic", [])[:4]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            results.append(f"• *{title}*\n{snippet}\n🔗 {link}")
        return "\n\n".join(results) if results else "Ничего не найдено"
    except Exception as e:
        logger.error(f"Search error: {e}")
        return "Ошибка поиска"

# ══════════════════════════════════════════
#  НАПОМИНАНИЯ
# ══════════════════════════════════════════
async def check_reminders(app):
    """Фоновая проверка напоминаний каждую минуту"""
    while True:
        try:
            reminders = load_reminders()
            now = datetime.now()
            remaining = []
            for r in reminders:
                remind_time = datetime.fromisoformat(r["time"])
                if now >= remind_time:
                    await app.bot.send_message(
                        r["chat_id"],
                        f"⏰ *Напоминание!*\n\n{r['text']}",
                        parse_mode="Markdown"
                    )
                else:
                    remaining.append(r)
            if len(remaining) != len(reminders):
                save_reminders(remaining)
        except Exception as e:
            logger.error(f"Reminder error: {e}")
        await asyncio.sleep(60)

def parse_reminder_time(text):
    """Парсит время из текста напоминания"""
    now = datetime.now()
    patterns = [
        (r'через (\d+) минут', lambda m: now + timedelta(minutes=int(m.group(1)))),
        (r'через (\d+) час', lambda m: now + timedelta(hours=int(m.group(1)))),
        (r'через (\d+) день', lambda m: now + timedelta(days=int(m.group(1)))),
        (r'завтра в (\d+):(\d+)', lambda m: (now + timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)))),
        (r'в (\d+):(\d+)', lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)))),
    ]
    for pattern, time_func in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return time_func(match), re.sub(pattern, '', text).strip()
    return None, text

# ══════════════════════════════════════════
#  ФОНОВАЯ ОБРАБОТКА
# ══════════════════════════════════════════
async def process_background(app, chat_id, text, data, image_bytes=None):
    try:
        context = build_context(data)

        # 📸 Анализ изображения
        if image_bytes:
            await app.bot.send_message(chat_id, "🔍 Анализирую изображение...")
            result = await analyze_image(image_bytes, text)
            if result:
                await app.bot.send_message(chat_id, f"🖼 *Анализ изображения:*\n\n{result}", parse_mode="Markdown")
            else:
                await app.bot.send_message(chat_id, "❌ Не удалось проанализировать изображение")
            return

        await app.bot.send_message(chat_id, "⚙️ Работаю в фоне... Занимайся своими делами!")

        result = None

        # 🌐 Поиск в интернете
        if needs_search(text):
            await app.bot.send_message(chat_id, "🌐 Ищу в интернете...")
            search_results = await search_web(text)
            search_context = f"{context}\n\nРезультаты поиска:\n{search_results}"
            result = await ask_groq_text(
                f"На основе результатов поиска ответь на вопрос: {text}\n\nДай полный структурированный ответ.",
                search_context
            )
            if result:
                await app.bot.send_message(chat_id, f"🌐 *Результаты из интернета:*\n\n{search_results[:2000]}", parse_mode="Markdown")

        # 💻 Код
        elif is_code_task(text):
            await app.bot.send_message(chat_id, "💻 Пишу полный код через Gemini...")
            result = await ask_gemini(text, context)
            if not result:
                await app.bot.send_message(chat_id, "⚠️ Gemini недоступен, пробую Groq...")
                result = await ask_groq_text(text, context)

        # 💬 Обычный ответ
        else:
            result = await ask_groq_text(text, context)
            if not result:
                result = await ask_gemini(text, context)

        if not result:
            await app.bot.send_message(chat_id, "❌ AI не ответил. Попробуй ещё раз.")
            return

        add_message(data, "Пользователь", text)
        add_message(data, "Агент", result[:400])
        if any(w in text.lower() for w in ["изучи", "расскажи", "объясни", "что такое"]):
            topic = text[:60]
            if topic not in data["learned_topics"]:
                data["learned_topics"].append(topic)
        save_data(data)

        # Отправка кода файлом
        if is_code_task(text):
            code = extract_code(result)
            if code and len(code) > 100:
                ext = detect_file_type(text, code)
                filename = f"code.{ext}"
                explanation = re.sub(r'```.*?```', '', result, flags=re.DOTALL).strip()
                if explanation and len(explanation) > 20:
                    for chunk in [explanation[i:i+4000] for i in range(0, len(explanation), 4000)]:
                        await app.bot.send_message(chat_id, f"✅ Готово!\n\n{chunk}")
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(code)
                size_kb = os.path.getsize(filename) / 1024
                with open(filename, 'rb') as f:
                    await app.bot.send_document(
                        chat_id, document=f, filename=filename,
                        caption=f"📁 `{filename}` • {size_kb:.1f} KB"
                    )
                os.remove(filename)
                return

        # Обычный текст
        full = "✅ Готово!\n\n" + result
        if len(full) > 4096:
            await app.bot.send_message(chat_id, "✅ Готово! Отправляю частями:")
            for i, chunk in enumerate([result[i:i+4000] for i in range(0, len(result), 4000)], 1):
                await app.bot.send_message(chat_id, f"Часть {i}:\n{chunk}")
        else:
            await app.bot.send_message(chat_id, full)

    except Exception as e:
        logger.error(f"Error: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {str(e)}")

# ══════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    current_chat = data["chats"][data["current_chat"]]["name"]
    await update.message.reply_text(
        f"👋 *Привет! Я твой персональный AI-агент*\n\n"
        f"📊 Статус:\n"
        f"├ 💬 Чат: {current_chat}\n"
        f"├ 📁 Чатов: {len(data['chats'])}\n"
        f"└ 📚 Изучено тем: {len(data['learned_topics'])}\n\n"
        f"🚀 Что умею:\n"
        f"├ 💻 Пишу код на 15+ языках → файлом\n"
        f"├ 🎤 Понимаю голосовые сообщения\n"
        f"├ 📸 Анализирую фото и картинки\n"
        f"├ 🌐 Ищу актуальную инфу в интернете\n"
        f"├ ⏰ Ставлю напоминания\n"
        f"└ 🧠 Помню историю всех чатов\n\n"
        f"👇 Используй кнопки или просто напиши!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🔄 *Бот перезапущен!* Всё готово 👇", parse_mode="Markdown", reply_markup=main_keyboard())

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
    keyboard.append([InlineKeyboardButton("➕ Новый чат", callback_data="new_chat_inline"), InlineKeyboardButton("🗑 Удалить", callback_data="show_delete")])
    await update.message.reply_text("💬 *Твои чаты:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def templates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 *Выбери шаблон:*\nНажми — скопируй — допиши задачу!", parse_mode="Markdown", reply_markup=templates_keyboard())

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 Что ищем? Напиши запрос:")
    context.user_data["waiting_search"] = True

async def reminders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = load_reminders()
    chat_id = update.effective_chat.id
    my_reminders = [r for r in reminders if r["chat_id"] == chat_id]
    keyboard = [[InlineKeyboardButton("➕ Добавить напоминание", callback_data="add_reminder")]]
    if my_reminders:
        for i, r in enumerate(my_reminders[:5]):
            t = datetime.fromisoformat(r["time"]).strftime("%d.%m %H:%M")
            keyboard.append([InlineKeyboardButton(f"🗑 {r['text'][:30]} ({t})", callback_data=f"del_reminder_{i}")])
    text = f"⏰ *Твои напоминания:*\n\n"
    if my_reminders:
        for r in my_reminders:
            t = datetime.fromisoformat(r["time"]).strftime("%d.%m в %H:%M")
            text += f"• {r['text']} — *{t}*\n"
    else:
        text += "Нет активных напоминаний\n"
    text += "\nФорматы: 'через 30 минут', 'через 2 часа', 'завтра в 10:00', 'в 15:30'"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    topics = "\n".join([f"• {t}" for t in data["learned_topics"][-15:]]) or "Пока ничего"
    current = data["chats"][data["current_chat"]]["name"]
    await update.message.reply_text(
        f"🧠 *Память:*\n\n"
        f"├ 💬 Чат: {current}\n"
        f"├ 📨 Сообщений: {len(get_current_history(data))}\n"
        f"└ 📁 Всего чатов: {len(data['chats'])}\n\n"
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
        "🎤 *Голос* — просто отправь голосовое\n"
        "📸 *Фото* — отправь картинку с подписью или без\n"
        "🌐 *Поиск* — кнопка или напиши 'найди...'\n"
        "⏰ *Напоминание* — напиши 'напомни через 1 час сделать...'\n"
        "💻 *Код* — напиши 'создай приложение...'\n\n"
        "📋 *Шаблоны* — готовые запросы для кода\n\n"
        "⌨️ Команды:\n"
        "/start — главное меню\n"
        "/restart — перезапустить\n"
        "/new — новый чат\n"
        "/chats — список чатов\n"
        "/search — поиск в интернете\n"
        "/reminders — напоминания\n"
        "/memory — память\n"
        "/clear — очистить чат",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )

# ══════════════════════════════════════════
#  ОБРАБОТКА МЕДИА
# ══════════════════════════════════════════
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("🎤 Распознаю голос...")
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        async with httpx.AsyncClient() as client:
            r = await client.get(file.file_path)
            voice_bytes = r.content
        text = await transcribe_voice(voice_bytes)
        if text:
            await update.message.reply_text(f"🎤 Ты сказал:\n_{text}_", parse_mode="Markdown")
            data = load_data()
            asyncio.create_task(process_background(context.application, chat_id, text, data))
        else:
            await update.message.reply_text("❌ Не удалось распознать голос. Попробуй ещё раз.")
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""
    await update.message.reply_text("📸 Анализирую изображение...")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        async with httpx.AsyncClient() as client:
            r = await client.get(file.file_path)
            image_bytes = r.content
        data = load_data()
        asyncio.create_task(process_background(context.application, chat_id, caption, data, image_bytes=image_bytes))
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# ══════════════════════════════════════════
#  КНОПКИ
# ══════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    chat_id = update.effective_chat.id

    if query.data.startswith("switch_"):
        key = query.data.replace("switch_", "")
        if key in data["chats"]:
            data["current_chat"] = key
            save_data(data)
            await query.edit_message_text(f"✅ Переключился на: *{data['chats'][key]['name']}*", parse_mode="Markdown")

    elif query.data == "new_chat_inline":
        await query.edit_message_text("✏️ Напиши название нового чата:")
        context.user_data["waiting_chat_name"] = True

    elif query.data == "show_delete":
        keyboard = [[InlineKeyboardButton(f"🗑 {chat['name']}", callback_data=f"delete_{key}")]
                    for key, chat in data["chats"].items() if key != "default"]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_chats")])
        if len(keyboard) == 1:
            await query.edit_message_text("❌ Нет чатов для удаления")
        else:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    elif query.data == "back_chats":
        current = data["current_chat"]
        keyboard = []
        for key, chat in data["chats"].items():
            mark = "✅ " if key == current else "💬 "
            keyboard.append([InlineKeyboardButton(f"{mark}{chat['name']} ({len(chat['history'])} сообщ.)", callback_data=f"switch_{key}")])
        keyboard.append([InlineKeyboardButton("➕ Новый чат", callback_data="new_chat_inline"), InlineKeyboardButton("🗑 Удалить", callback_data="show_delete")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("delete_"):
        key = query.data.replace("delete_", "")
        if key in data["chats"]:
            name = data["chats"][key]["name"]
            del data["chats"][key]
            if data["current_chat"] == key:
                data["current_chat"] = list(data["chats"].keys())[0]
            save_data(data)
            await query.edit_message_text(f"🗑 Чат *{name}* удалён!", parse_mode="Markdown")

    elif query.data.startswith("tmpl_"):
        idx = int(query.data.replace("tmpl_", ""))
        keys = list(TEMPLATES.keys())
        if idx < len(keys):
            key = keys[idx]
            await query.edit_message_text(
                f"📋 *{key}*\n\nСкопируй и допиши:\n\n`{TEMPLATES[key]}`",
                parse_mode="Markdown"
            )

    elif query.data == "add_reminder":
        await query.edit_message_text(
            "⏰ Напиши напоминание в формате:\n\n"
            "*напомни через 30 минут позвонить маме*\n"
            "*напомни в 15:30 встреча*\n"
            "*напомни завтра в 10:00 купить продукты*",
            parse_mode="Markdown"
        )
        context.user_data["waiting_reminder"] = True

    elif query.data.startswith("del_reminder_"):
        idx = int(query.data.replace("del_reminder_", ""))
        reminders = load_reminders()
        my_reminders = [r for r in reminders if r["chat_id"] == chat_id]
        if idx < len(my_reminders):
            reminders.remove(my_reminders[idx])
            save_reminders(reminders)
            await query.edit_message_text("🗑 Напоминание удалено!")

# ══════════════════════════════════════════
#  ОБРАБОТКА ТЕКСТА
# ══════════════════════════════════════════
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # Кнопки меню
    actions = {
        "💬 Новый чат": new_chat_cmd,
        "📂 Мои чаты": list_chats_cmd,
        "📋 Шаблоны": templates_cmd,
        "🔍 Поиск в сети": search_cmd,
        "⏰ Напоминания": reminders_cmd,
        "🧠 Память": memory_cmd,
        "🗑 Очистить чат": clear_cmd,
        "❓ Помощь": help_cmd,
    }
    if text in actions:
        await actions[text](update, context)
        return

    # Ожидание названия чата
    if context.user_data.get("waiting_chat_name"):
        context.user_data["waiting_chat_name"] = False
        data = load_data()
        key = f"chat_{int(datetime.now().timestamp())}"
        data["chats"][key] = {"name": text, "history": [], "created": datetime.now().strftime("%d.%m %H:%M")}
        data["current_chat"] = key
        save_data(data)
        await update.message.reply_text(f"✅ Новый чат: *{text}*", parse_mode="Markdown", reply_markup=main_keyboard())
        return

    # Ожидание поискового запроса
    if context.user_data.get("waiting_search"):
        context.user_data["waiting_search"] = False
        await update.message.reply_text("🌐 Ищу в интернете...")
        results = await search_web(text)
        data = load_data()
        search_context = f"{build_context(data)}\n\nРезультаты поиска:\n{results}"
        answer = await ask_groq_text(f"Ответь на вопрос на основе поиска: {text}", search_context)
        await update.message.reply_text(f"🌐 *Найдено:*\n\n{results[:2000]}", parse_mode="Markdown")
        if answer:
            await update.message.reply_text(f"💡 *Итог:*\n\n{answer[:2000]}", parse_mode="Markdown")
        return

    # Напоминание из текста
    if any(w in text.lower() for w in ["напомни", "напоминание", "поставь напоминание"]):
        remind_time, remind_text = parse_reminder_time(text)
        if remind_time:
            reminders = load_reminders()
            reminders.append({"chat_id": chat_id, "text": remind_text, "time": remind_time.isoformat()})
            save_reminders(reminders)
            t = remind_time.strftime("%d.%m в %H:%M")
            await update.message.reply_text(f"⏰ Напоминание поставлено!\n\n📝 {remind_text}\n🕐 {t}", reply_markup=main_keyboard())
            return

    # Ожидание напоминания
    if context.user_data.get("waiting_reminder"):
        context.user_data["waiting_reminder"] = False
        remind_time, remind_text = parse_reminder_time(text)
        if remind_time:
            reminders = load_reminders()
            reminders.append({"chat_id": chat_id, "text": remind_text, "time": remind_time.isoformat()})
            save_reminders(reminders)
            t = remind_time.strftime("%d.%m в %H:%M")
            await update.message.reply_text(f"⏰ Поставил напоминание!\n\n📝 {remind_text}\n🕐 {t}", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ Не понял время. Попробуй: 'напомни через 1 час сделать что-то'")
        return

    data = load_data()
    asyncio.create_task(process_background(context.application, chat_id, text, data))

# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════
async def post_init(app):
    asyncio.create_task(check_reminders(app))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("new", new_chat_cmd))
    app.add_handler(CommandHandler("chats", list_chats_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("reminders", reminders_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
