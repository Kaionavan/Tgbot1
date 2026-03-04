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
#  КЛЮЧИ
# ══════════════════════════════════════════
TELEGRAM_TOKEN = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GROQ_KEY       = "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"
GEMINI_KEY     = "AIzaSyD21rIGQxhzh6HXvb05Tkc5SYLBsFVn5II"
DEEPSEEK_KEY   = "sk-5c112016a71c444e88ea825e3f8c7d4f"
COHERE_KEY     = "UwiOG7P74hXPKzrSK4rk2P2xaRxw2Bc9R3PhXmT2"
OPENROUTER_KEY = "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"
SERPER_KEY     = "2def7b1526652c4af691804cd8ed41231666d0be"

DATA_FILE      = "data.json"
REMINDERS_FILE = "reminders.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
#  ШАБЛОНЫ
# ══════════════════════════════════════════
TEMPLATES = {
    "🌐 Сайт":        "Напиши полный HTML файл с красивым CSS дизайном и JS, всё в одном файле. Сделай: ",
    "🐍 Python":      "Напиши полный рабочий Python код без сокращений. Задача: ",
    "🤖 Telegram бот":"Напиши полный код Telegram бота на Python. Бот должен: ",
    "🎮 Игра":        "Напиши полную игру на Python или HTML/JS. Игра: ",
    "📱 Приложение":  "Напиши полное приложение, весь код целиком. Приложение: ",
    "🗄️ База данных": "Напиши Python код с SQLite базой данных. Функционал: ",
    "🎯 C++":         "Напиши полный рабочий C++ код. Задача: ",
    "⚡ JavaScript":  "Напиши полный JavaScript код в одном файле. Задача: ",
    "📚 Объяснить":   "Объясни простым языком с примерами: ",
    "🔍 Поиск":       "Найди актуальную информацию в интернете про: ",
}

# ══════════════════════════════════════════
#  КЛАВИАТУРА
# ══════════════════════════════════════════
def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💬 Новый чат"),    KeyboardButton("📂 Мои чаты")],
        [KeyboardButton("📋 Шаблоны"),      KeyboardButton("🔍 Поиск")],
        [KeyboardButton("⏰ Напоминания"),   KeyboardButton("🧠 Память")],
        [KeyboardButton("📡 Статус AI"),    KeyboardButton("❓ Помощь")],
    ], resize_keyboard=True, persistent=True)

# ══════════════════════════════════════════
#  РАБОТА С ДАННЫМИ
# ══════════════════════════════════════════
def load_data():
    if Path(DATA_FILE).exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "current": "main",
        "chats": {
            "main": {"name": "Основной чат", "history": [], "created": datetime.now().strftime("%d.%m.%Y")}
        },
        "topics": [],
        "last_code": ""
    }

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def load_reminders():
    if Path(REMINDERS_FILE).exists():
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_reminders(r):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)

def history(d):
    return d["chats"][d["current"]]["history"]

def add_msg(d, role, text):
    h = history(d)
    h.append({"role": role, "text": text[:500], "time": datetime.now().strftime("%d.%m %H:%M")})
    if len(h) > 50:
        d["chats"][d["current"]]["history"] = h[-50:]

def make_context(d):
    h = history(d)[-8:]
    h_text = "\n".join([f"{m['role']}: {m['text']}" for m in h])
    topics = ", ".join(d["topics"][-10:]) or "пока ничего"
    chat_name = d["chats"][d["current"]]["name"]
    last_code = d.get("last_code", "")
    code_ctx = f"\nПоследний код (контекст):\n{last_code[:400]}" if last_code else ""
    return (
        f"Ты профессиональный AI-агент и разработчик. Отвечай на русском.\n"
        f"Чат: {chat_name} | Темы: {topics}\n"
        f"История:\n{h_text}{code_ctx}\n"
        f"ПРАВИЛО: Код пиши ПОЛНОСТЬЮ без сокращений и заглушек!"
    )

def make_code_prompt(task):
    return (
        f"Задача: {task}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. Напиши ПОЛНЫЙ код от первой до последней строки\n"
        f"2. НЕ используй заглушки # TODO или # здесь ваш код\n"
        f"3. Добавь все импорты\n"
        f"4. Код должен запускаться без изменений\n"
        f"5. Добавь обработку ошибок\n"
        f"6. Комментарии на русском\n"
        f"Пиши весь код целиком:"
    )

def extract_code(text):
    codes = re.findall(r'```(?:\w+\n)?(.*?)```', text, re.DOTALL)
    if not codes:
        codes = re.findall(r'```(.*?)```', text, re.DOTALL)
    if codes:
        best = max(codes, key=len).strip()
        return best if len(best) > 50 else None
    return None

def get_ext(prompt, code):
    p = prompt.lower()
    if any(x in p for x in ['html', 'сайт', 'веб']): return 'html'
    if 'css' in p: return 'css'
    if any(x in p for x in ['javascript', ' js ']): return 'js'
    if any(x in p for x in ['c++', 'cpp']): return 'cpp'
    if any(x in p for x in ['c#', 'шарп']): return 'cs'
    if 'kotlin' in p: return 'kt'
    if 'swift' in p: return 'swift'
    if 'rust' in p: return 'rs'
    if any(x in p for x in ['golang', ' go ']): return 'go'
    if 'php' in p: return 'php'
    if 'ruby' in p: return 'rb'
    if any(x in p for x in ['bash', 'shell']): return 'sh'
    if 'sql' in p: return 'sql'
    if any(x in p for x in ['dart', 'flutter']): return 'dart'
    if 'java ' in p: return 'java'
    if code:
        if '#include' in code or 'cout' in code: return 'cpp'
        if 'using System' in code: return 'cs'
        if 'console.log' in code: return 'js'
        if '<html' in code: return 'html'
    return 'py'

def is_code(text):
    return any(k in text.lower() for k in [
        "создай","напиши","сделай","код","приложение","скрипт",
        "программу","бот","сайт","функцию","калькулятор","игру","база данных"
    ])

def is_search(text):
    return any(k in text.lower() for k in [
        "найди","поищи","что сейчас","новости","актуально","курс","погода","цена"
    ])

# ══════════════════════════════════════════
#  AI ПРОВАЙДЕРЫ
# ══════════════════════════════════════════
async def ask_groq(prompt, ctx):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role": "system", "content": ctx}, {"role": "user", "content": prompt}],
                      "max_tokens": 8000, "temperature": 0.3}
            )
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None

async def ask_gemini(prompt, ctx):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [{"text": f"{ctx}\n\n{prompt}\n\nПиши ПОЛНЫЙ код!"}]}],
                      "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3}}
            )
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini: {e}")
        return None

async def ask_openrouter(prompt, ctx):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={"model": "deepseek/deepseek-chat",
                      "messages": [{"role": "system", "content": ctx}, {"role": "user", "content": prompt}],
                      "max_tokens": 8000}
            )
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None

async def ask_cohere(prompt, ctx):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.cohere.ai/v1/chat",
                headers={"Authorization": f"Bearer {COHERE_KEY}", "Content-Type": "application/json"},
                json={"model": "command-r-plus", "message": prompt, "preamble": ctx, "max_tokens": 4000}
            )
            return r.json()["text"]
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

async def ask_deepseek(prompt, ctx):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "system", "content": ctx}, {"role": "user", "content": prompt}],
                      "max_tokens": 8000}
            )
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"DeepSeek: {e}")
        return None

async def best_ai(prompt, ctx, for_code=False):
    """Пробует провайдеры по очереди"""
    order = (
        [ask_openrouter, ask_gemini, ask_groq, ask_cohere]
        if for_code else
        [ask_groq, ask_openrouter, ask_gemini, ask_cohere]
    )
    names = {ask_groq: "Groq", ask_gemini: "Gemini",
             ask_openrouter: "OpenRouter", ask_cohere: "Cohere", ask_deepseek: "DeepSeek"}
    for fn in order:
        result = await fn(prompt, ctx)
        if result:
            return result, names[fn]
    return None, None

async def smart_code(task, ctx):
    """Умная генерация — если код короткий, просит дописать"""
    result, ai_name = await best_ai(make_code_prompt(task), ctx, for_code=True)
    if not result:
        return None, None
    code = extract_code(result)
    if code and len(code) < 800:
        expand = (
            f"Код слишком короткий. Задача: {task}\n"
            f"Предыдущий код:\n```\n{code}\n```\n"
            f"Допиши полностью — добавь все функции, UI, обработку ошибок. Пиши весь код заново:"
        )
        result2, ai2 = await best_ai(expand, ctx, for_code=True)
        if result2 and len(result2) > len(result):
            return result2, f"{ai_name}+доп"
    return result, ai_name

async def check_all_ai():
    """Параллельная проверка всех провайдеров"""
    test = "Скажи ок"
    ctx = "Ты помощник"
    providers = [
        ("🟢 Groq",       ask_groq),
        ("💎 Gemini",      ask_gemini),
        ("🔷 OpenRouter",  ask_openrouter),
        ("🟡 Cohere",      ask_cohere),
        ("🔵 DeepSeek",    ask_deepseek),
    ]
    async def check(name, fn):
        try:
            r = await asyncio.wait_for(fn(test, ctx), timeout=8)
            return name, "✅ Работает" if r else "❌ Нет ответа"
        except asyncio.TimeoutError:
            return name, "⏱ Таймаут"
        except Exception:
            return name, "❌ Ошибка"
    results = await asyncio.gather(*[check(n, f) for n, f in providers])
    return dict(results)

# ══════════════════════════════════════════
#  ГОЛОС И ФОТО
# ══════════════════════════════════════════
async def voice_to_text(data):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files={"file": ("audio.ogg", data, "audio/ogg"), "model": (None, "whisper-large-v3")}
            )
            return r.json().get("text", "")
    except Exception as e:
        logger.error(f"Whisper: {e}")
        return ""

async def analyze_photo(img_bytes, prompt):
    try:
        import base64
        b64 = base64.b64encode(img_bytes).decode()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    {"text": prompt or "Опиши подробно что видишь. Отвечай на русском."}
                ]}]}
            )
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Vision: {e}")
        return None

# ══════════════════════════════════════════
#  ПОИСК
# ══════════════════════════════════════════
async def web_search(query):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
                json={"q": query, "gl": "ru", "hl": "ru", "num": 5}
            )
            data = r.json()
        out = []
        if "answerBox" in data:
            ans = data["answerBox"].get("answer") or data["answerBox"].get("snippet", "")
            if ans: out.append(f"📌 {ans}")
        for item in data.get("organic", [])[:4]:
            out.append(f"• *{item.get('title','')}*\n{item.get('snippet','')}")
        return "\n\n".join(out) if out else "Ничего не найдено"
    except Exception as e:
        logger.error(f"Search: {e}")
        return "Ошибка поиска"

# ══════════════════════════════════════════
#  НАПОМИНАНИЯ
# ══════════════════════════════════════════
def parse_time(text):
    now = datetime.now()
    checks = [
        (r'через (\d+) минут', lambda m: now + timedelta(minutes=int(m.group(1)))),
        (r'через (\d+) час',   lambda m: now + timedelta(hours=int(m.group(1)))),
        (r'через (\d+) день',  lambda m: now + timedelta(days=int(m.group(1)))),
        (r'завтра в (\d+):(\d+)', lambda m: (now + timedelta(days=1)).replace(
            hour=int(m.group(1)), minute=int(m.group(2)), second=0)),
        (r'в (\d+):(\d+)', lambda m: (
            now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0)
            if now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0) > now
            else now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0) + timedelta(days=1)
        )),
    ]
    for pattern, fn in checks:
        m = re.search(pattern, text.lower())
        if m:
            return fn(m), re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
    return None, text

async def reminder_loop(app):
    while True:
        try:
            rems = load_reminders()
            now = datetime.now()
            keep = []
            for r in rems:
                if now >= datetime.fromisoformat(r["time"]):
                    await app.bot.send_message(
                        r["chat_id"],
                        f"⏰ *Напоминание!*\n\n{r['text']}",
                        parse_mode="Markdown"
                    )
                else:
                    keep.append(r)
            if len(keep) != len(rems):
                save_reminders(keep)
        except Exception as e:
            logger.error(f"Reminder loop: {e}")
        await asyncio.sleep(60)

# ══════════════════════════════════════════
#  ОБРАБОТКА ЗАПРОСОВ
# ══════════════════════════════════════════
async def process(app, chat_id, text, d, img=None):
    try:
        ctx = make_context(d)

        if img is not None:
            await app.bot.send_message(chat_id, "🔍 Анализирую изображение...")
            result = await analyze_photo(img, text)
            if result:
                await send_long(app, chat_id, f"🖼 *Анализ:*\n\n{result}")
            else:
                await app.bot.send_message(chat_id, "❌ Не удалось проанализировать")
            return

        await app.bot.send_message(chat_id, "⚙️ Работаю... Занимайся своими делами!")

        result, ai_name = None, None

        if is_search(text):
            await app.bot.send_message(chat_id, "🌐 Ищу в интернете...")
            found = await web_search(text)
            result, ai_name = await best_ai(
                f"Ответь на вопрос используя результаты поиска: {text}",
                ctx + f"\nРезультаты поиска:\n{found}"
            )
            if found and found != "Ошибка поиска":
                await send_long(app, chat_id, f"🌐 *Найдено:*\n\n{found}")

        elif is_code(text):
            await app.bot.send_message(chat_id, "💻 Пишу полный код...")
            result, ai_name = await smart_code(text, ctx)

        else:
            result, ai_name = await best_ai(text, ctx)

        if not result:
            await app.bot.send_message(chat_id, "❌ Все AI не ответили. Попробуй позже.")
            return

        add_msg(d, "Пользователь", text)
        add_msg(d, "Агент", result[:400])

        if any(w in text.lower() for w in ["изучи","расскажи","объясни","что такое"]):
            if text[:60] not in d["topics"]:
                d["topics"].append(text[:60])

        if is_code(text):
            code = extract_code(result)
            if code and len(code) > 100:
                d["last_code"] = code[:800]
                save_data(d)
                ext = get_ext(text, code)
                fname = f"code.{ext}"
                explanation = re.sub(r'```.*?```', '', result, flags=re.DOTALL).strip()
                if explanation and len(explanation) > 20:
                    await send_long(app, chat_id, f"✅ Готово! _{ai_name}_\n\n{explanation}")
                with open(fname, 'w', encoding='utf-8') as f:
                    f.write(code)
                kb = os.path.getsize(fname) / 1024
                lines = len(code.splitlines())
                with open(fname, 'rb') as f:
                    await app.bot.send_document(
                        chat_id, f, filename=fname,
                        caption=f"📁 `{fname}` • {kb:.1f} KB • {lines} строк\n🤖 {ai_name}"
                    )
                os.remove(fname)
                save_data(d)
                return

        save_data(d)
        await send_long(app, chat_id, f"✅ Готово! _{ai_name}_\n\n{result}")

    except Exception as e:
        logger.error(f"process: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {e}")

async def send_long(app, chat_id, text):
    """Отправляет длинный текст частями"""
    if len(text) <= 4096:
        try:
            await app.bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception:
            await app.bot.send_message(chat_id, text)
        return
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for i, chunk in enumerate(chunks, 1):
        try:
            await app.bot.send_message(chat_id, f"📄 *{i}/{len(chunks)}:*\n\n{chunk}", parse_mode="Markdown")
        except Exception:
            await app.bot.send_message(chat_id, chunk)
        await asyncio.sleep(0.3)

# ══════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = load_data()
    await update.message.reply_text(
        f"👋 *Привет! Я твой AI-агент*\n\n"
        f"├ 💬 Чат: {d['chats'][d['current']]['name']}\n"
        f"├ 📁 Чатов: {len(d['chats'])}\n"
        f"└ 📚 Тем: {len(d['topics'])}\n\n"
        f"🤖 *5 AI провайдеров:*\n"
        f"Groq • Gemini • OpenRouter • Cohere • DeepSeek\n\n"
        f"🚀 *Умею:*\n"
        f"├ 💻 Код на 15+ языках → файлом\n"
        f"├ 🎤 Голосовые сообщения\n"
        f"├ 📸 Анализ фото\n"
        f"├ 🌐 Поиск в интернете\n"
        f"└ ⏰ Напоминания\n\n"
        f"👇 Используй кнопки!",
        parse_mode="Markdown", reply_markup=main_kb()
    )

async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🔄 *Бот перезапущен!*\nВсё готово 👇",
        parse_mode="Markdown", reply_markup=main_kb()
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 Проверяю все AI... подожди ~8 сек")
    results = await check_all_ai()
    text = "📡 *Статус AI провайдеров:*\n\n"
    for name, status in results.items():
        text += f"{name}: {status}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_kb())

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Введи название нового чата:")
    context.user_data["wait"] = "chat_name"

async def cmd_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = load_data()
    cur = d["current"]
    kb = []
    for key, chat in d["chats"].items():
        mark = "✅ " if key == cur else "💬 "
        kb.append([InlineKeyboardButton(
            f"{mark}{chat['name']} ({len(chat['history'])} сообщ.)",
            callback_data=f"sw_{key}"
        )])
    kb.append([
        InlineKeyboardButton("➕ Новый", callback_data="new_chat"),
        InlineKeyboardButton("🗑 Удалить", callback_data="del_menu")
    ])
    await update.message.reply_text(
        "💬 *Твои чаты:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 Что ищем?")
    context.user_data["wait"] = "search"

async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rems = [r for r in load_reminders() if r["chat_id"] == chat_id]
    kb = [[InlineKeyboardButton("➕ Добавить напоминание", callback_data="add_rem")]]
    text = "⏰ *Напоминания:*\n\n"
    if rems:
        for i, r in enumerate(rems[:5]):
            t = datetime.fromisoformat(r["time"]).strftime("%d.%m в %H:%M")
            text += f"• {r['text']} — *{t}*\n"
            kb.append([InlineKeyboardButton(f"🗑 {r['text'][:30]}", callback_data=f"del_rem_{i}")])
    else:
        text += (
            "Нет активных\n\n"
            "Примеры:\n"
            "• _напомни через 30 минут позвонить_\n"
            "• _напомни в 15:30 встреча_\n"
            "• _напомни завтра в 10:00 купить_"
        )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = load_data()
    topics = "\n".join([f"• {t}" for t in d["topics"][-15:]]) or "Пока ничего"
    cur = d["chats"][d["current"]]["name"]
    await update.message.reply_text(
        f"🧠 *Память:*\n\n"
        f"├ 💬 Чат: {cur}\n"
        f"├ 📨 Сообщений: {len(history(d))}\n"
        f"└ 📁 Чатов: {len(d['chats'])}\n\n"
        f"📚 *Изученные темы:*\n{topics}",
        parse_mode="Markdown", reply_markup=main_kb()
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = load_data()
    name = d["chats"][d["current"]]["name"]
    d["chats"][d["current"]]["history"] = []
    d["last_code"] = ""
    save_data(d)
    await update.message.reply_text(f"🗑 Чат «{name}» очищен!", reply_markup=main_kb())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Как пользоваться:*\n\n"
        "🎤 Отправь голосовое — распознаю\n"
        "📸 Отправь фото — опишу\n"
        "🌐 Кнопка Поиск или напиши _найди..._\n"
        "⏰ Напиши _напомни через 1 час..._\n"
        "💻 Напиши _создай приложение..._\n"
        "📡 Кнопка Статус AI — проверить провайдеры\n\n"
        "⌨️ *Команды:*\n"
        "/start — главное меню\n"
        "/restart — перезапустить\n"
        "/status — статус AI\n"
        "/new — новый чат\n"
        "/chats — список чатов\n"
        "/search — поиск\n"
        "/reminders — напоминания\n"
        "/memory — память\n"
        "/clear — очистить чат",
        parse_mode="Markdown", reply_markup=main_kb()
    )

# ══════════════════════════════════════════
#  МЕДИА
# ══════════════════════════════════════════
async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("🎤 Распознаю голос...")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        async with httpx.AsyncClient() as c:
            r = await c.get(file.file_path)
        text = await voice_to_text(r.content)
        if text:
            await update.message.reply_text(f"🎤 Ты сказал:\n_{text}_", parse_mode="Markdown")
            d = load_data()
            asyncio.create_task(process(context.application, chat_id, text, d))
        else:
            await update.message.reply_text("❌ Не удалось распознать")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""
    await update.message.reply_text("📸 Анализирую...")
    try:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        async with httpx.AsyncClient() as c:
            r = await c.get(file.file_path)
        d = load_data()
        asyncio.create_task(process(context.application, chat_id, caption, d, img=r.content))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ══════════════════════════════════════════
#  КНОПКИ
# ══════════════════════════════════════════
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = load_data()
    chat_id = update.effective_chat.id
    data = q.data

    if data.startswith("sw_"):
        key = data[3:]
        if key in d["chats"]:
            d["current"] = key
            save_data(d)
            await q.edit_message_text(
                f"✅ Чат: *{d['chats'][key]['name']}*",
                parse_mode="Markdown"
            )

    elif data == "new_chat":
        await q.edit_message_text("✏️ Напиши название нового чата:")
        context.user_data["wait"] = "chat_name"

    elif data == "del_menu":
        kb = [[InlineKeyboardButton(f"🗑 {c['name']}", callback_data=f"del_{k}")]
              for k, c in d["chats"].items() if k != "main"]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
        if len(kb) == 1:
            await q.edit_message_text("❌ Нет чатов для удаления")
        else:
            await q.edit_message_reply_markup(InlineKeyboardMarkup(kb))

    elif data == "back":
        cur = d["current"]
        kb = [[InlineKeyboardButton(
            ("✅ " if k == cur else "💬 ") + f"{c['name']} ({len(c['history'])} сообщ.)",
            callback_data=f"sw_{k}"
        )] for k, c in d["chats"].items()]
        kb.append([
            InlineKeyboardButton("➕ Новый", callback_data="new_chat"),
            InlineKeyboardButton("🗑 Удалить", callback_data="del_menu")
        ])
        await q.edit_message_reply_markup(InlineKeyboardMarkup(kb))

    elif data.startswith("del_rem_"):
        idx = int(data[8:])
        rems = load_reminders()
        my = [r for r in rems if r["chat_id"] == chat_id]
        if idx < len(my):
            rems.remove(my[idx])
            save_reminders(rems)
            await q.edit_message_text("🗑 Напоминание удалено!")

    elif data.startswith("del_"):
        key = data[4:]
        if key in d["chats"] and key != "main":
            name = d["chats"][key]["name"]
            del d["chats"][key]
            if d["current"] == key:
                d["current"] = list(d["chats"].keys())[0]
            save_data(d)
            await q.edit_message_text(f"🗑 Чат *{name}* удалён!", parse_mode="Markdown")
        elif key == "main":
            await q.answer("❌ Основной чат нельзя удалить", show_alert=True)

    elif data.startswith("tmpl_"):
        idx = int(data[5:])
        keys = list(TEMPLATES.keys())
        if idx < len(keys):
            k = keys[idx]
            await q.edit_message_text(
                f"📋 *{k}*\n\nСкопируй и допиши:\n\n`{TEMPLATES[k]}`",
                parse_mode="Markdown"
            )

    elif data == "add_rem":
        await q.edit_message_text(
            "⏰ Напиши напоминание:\n\n"
            "_напомни через 30 минут позвонить_\n"
            "_напомни в 15:30 встреча_\n"
            "_напомни завтра в 10:00 купить_",
            parse_mode="Markdown"
        )
        context.user_data["wait"] = "reminder"


# ══════════════════════════════════════════
#  ТЕКСТОВЫЕ СООБЩЕНИЯ
# ══════════════════════════════════════════
async def app_send(context, chat_id, text):
    """Отправляет текст через context.bot частями"""
    if len(text) <= 4096:
        try:
            await context.bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id, text)
        return
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for i, chunk in enumerate(chunks, 1):
        try:
            await context.bot.send_message(chat_id, f"📄 *{i}/{len(chunks)}:*\n\n{chunk}", parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id, chunk)
        await asyncio.sleep(0.3)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # Кнопки меню
    menu = {
        "💬 Новый чат":   cmd_new,
        "📂 Мои чаты":    cmd_chats,
        "📋 Шаблоны":     on_templates,
        "🔍 Поиск":       cmd_search,
        "⏰ Напоминания":  cmd_reminders,
        "🧠 Память":       cmd_memory,
        "📡 Статус AI":    cmd_status,
        "❓ Помощь":       cmd_help,
    }
    if text in menu:
        await menu[text](update, context)
        return

    wait = context.user_data.get("wait")

    if wait == "chat_name":
        context.user_data.pop("wait")
        d = load_data()
        key = f"c{int(datetime.now().timestamp())}"
        d["chats"][key] = {"name": text, "history": [], "created": datetime.now().strftime("%d.%m %H:%M")}
        d["current"] = key
        save_data(d)
        await update.message.reply_text(
            f"✅ Новый чат: *{text}*", parse_mode="Markdown", reply_markup=main_kb()
        )
        return

    if wait == "search":
        context.user_data.pop("wait")
        await update.message.reply_text("🌐 Ищу в интернете...")
        found = await web_search(text)
        await context.bot.send_message(chat_id, f"🌐 *Найдено:*\n\n{found[:3000]}", parse_mode="Markdown")
        d = load_data()
        answer, ai = await best_ai(
            f"Кратко ответь на вопрос используя результаты поиска: {text}",
            make_context(d) + f"\nРезультаты поиска:\n{found}"
        )
        if answer:
            await context.bot.send_message(chat_id, f"💡 *Итог ({ai}):*\n\n{answer[:3000]}", parse_mode="Markdown")
        return

    if wait == "reminder":
        context.user_data.pop("wait")
        t, txt = parse_time(text)
        if t:
            rems = load_reminders()
            rems.append({"chat_id": chat_id, "text": txt, "time": t.isoformat()})
            save_reminders(rems)
            await update.message.reply_text(
                f"⏰ Поставил!\n\n📝 {txt}\n🕐 {t.strftime('%d.%m в %H:%M')}",
                reply_markup=main_kb()
            )
        else:
            await update.message.reply_text("❌ Не понял время. Пример: _напомни через 1 час сделать что-то_")
        return

    # Напоминание из обычного сообщения
    if any(w in text.lower() for w in ["напомни", "поставь напоминание"]):
        t, txt = parse_time(text)
        if t:
            rems = load_reminders()
            rems.append({"chat_id": chat_id, "text": txt, "time": t.isoformat()})
            save_reminders(rems)
            await update.message.reply_text(
                f"⏰ Поставил!\n\n📝 {txt}\n🕐 {t.strftime('%d.%m в %H:%M')}",
                reply_markup=main_kb()
            )
            return

    d = load_data()
    asyncio.create_task(process(context.application, chat_id, text, d))

async def on_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = list(TEMPLATES.keys())
    kb = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(items[i], callback_data=f"tmpl_{i}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(items[i+1], callback_data=f"tmpl_{i+1}"))
        kb.append(row)
    await update.message.reply_text(
        "📋 *Выбери шаблон:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════
async def post_init(app):
    asyncio.create_task(reminder_loop(app))
    await app.bot.set_my_commands([
        ("start",     "🚀 Главное меню"),
        ("restart",   "🔄 Перезапустить бота"),
        ("status",    "📡 Статус AI провайдеров"),
        ("new",       "💬 Новый чат"),
        ("chats",     "📂 Список чатов"),
        ("search",    "🌐 Поиск в интернете"),
        ("reminders", "⏰ Напоминания"),
        ("memory",    "🧠 Память"),
        ("clear",     "🗑 Очистить чат"),
        ("help",      "❓ Помощь"),
    ])

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("restart",   cmd_restart))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("new",       cmd_new))
    app.add_handler(CommandHandler("chats",     cmd_chats))
    app.add_handler(CommandHandler("search",    cmd_search))
    app.add_handler(CommandHandler("reminders", cmd_reminders))
    app.add_handler(CommandHandler("memory",    cmd_memory))
    app.add_handler(CommandHandler("clear",     cmd_clear))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
