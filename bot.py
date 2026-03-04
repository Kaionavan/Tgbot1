import json
import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GROQ_API_KEY = "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"
DEEPSEEK_API_KEY = "sk-5c112016a71c444e88ea825e3f8c7d4f"
DATA_FILE = "data.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main_keyboard():
    keyboard = [
        [KeyboardButton("💬 Новый чат"), KeyboardButton("📂 Мои чаты")],
        [KeyboardButton("🧠 Память"), KeyboardButton("🗑 Очистить чат")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

def load_data():
    if Path(DATA_FILE).exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "current_chat": "default",
        "chats": {
            "default": {
                "name": "Основной чат",
                "history": [],
                "created": datetime.now().strftime("%d.%m.%Y")
            }
        },
        "learned_topics": []
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
    return f"""Ты профессиональный AI-агент разработчик. 
Текущий чат: {chat_name}
Изученные темы: {topics}
История: {history_text}
ВАЖНО: Когда пишешь код — пиши МАКСИМАЛЬНО ПОЛНЫЙ и РАБОЧИЙ код, не сокращай, не пиши заглушки. Пиши весь код целиком."""

def extract_code(text):
    for pattern in [r'```\w*\n(.*?)```', r'```(.*?)```']:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            longest = max(matches, key=len)
            if len(longest.strip()) > 50:
                return longest.strip()
    return None

def detect_file_type(prompt, code):
    p = prompt.lower()
    if 'html' in p or 'сайт' in p or 'веб' in p: return 'html'
    if 'css' in p: return 'css'
    if 'javascript' in p or ' js ' in p: return 'js'
    if 'typescript' in p: return 'ts'
    if 'c++' in p or 'cpp' in p: return 'cpp'
    if 'c#' in p or 'шарп' in p or 'csharp' in p: return 'cs'
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
                "программу", "бот", "сайт", "функцию", "калькулятор", "игру", "напиши код"]
    return any(k in text.lower() for k in keywords)

# ====== AI — DeepSeek для кода, Groq для остального ======
async def ask_deepseek(prompt, context):
    try:
        url = "https://api.deepseek.com/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 8000
        }
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(url, json=payload, headers=headers)
            data = r.json()
            logger.info(f"DeepSeek status: {r.status_code}")
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return None

async def ask_groq(prompt, context):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 8000
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, json=payload, headers=headers)
            data = r.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

async def process_background(app, chat_id, text, data):
    try:
        context = build_context(data)
        await app.bot.send_message(chat_id, "⚙️ Работаю... Занимайся своими делами!")

        # Для кода — DeepSeek, для объяснений — Groq
        if is_code_task(text):
            await app.bot.send_message(chat_id, "💻 Пишу код через DeepSeek (мощный режим)...")
            result = await ask_deepseek(text, context)
            if not result:
                await app.bot.send_message(chat_id, "⚠️ DeepSeek недоступен, пробую Groq...")
                result = await ask_groq(text, context)
        else:
            result = await ask_groq(text, context)
            if not result:
                result = await ask_deepseek(text, context)

        if not result:
            await app.bot.send_message(chat_id, "❌ Оба AI не ответили. Попробуй позже.")
            return

        add_message(data, "Пользователь", text)
        add_message(data, "Агент", result[:400])

        if any(w in text.lower() for w in ["изучи", "расскажи", "объясни", "что такое"]):
            topic = text[:60]
            if topic not in data["learned_topics"]:
                data["learned_topics"].append(topic)

        save_data(data)

        # Если код — отправляем файл
        if is_code_task(text):
            code = extract_code(result)
            if code:
                ext = detect_file_type(text, code)
                filename = f"code.{ext}"
                explanation = re.sub(r'```.*?```', '', result, flags=re.DOTALL).strip()
                if explanation:
                    msg = f"✅ Готово!\n\n{explanation}"
                    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
                        await app.bot.send_message(chat_id, chunk)
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

        # Обычный ответ
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

# ====== КОМАНДЫ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой персональный AI-агент.\n\n"
        "Используй кнопки внизу 👇",
        reply_markup=main_keyboard()
    )

async def new_chat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введи название нового чата:")
    context.user_data["waiting_chat_name"] = True

async def list_chats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    current = data["current_chat"]
    keyboard = []
    for key, chat in data["chats"].items():
        mark = "✅ " if key == current else ""
        keyboard.append([InlineKeyboardButton(
            f"{mark}{chat['name']} ({len(chat['history'])} сообщ.)",
            callback_data=f"switch_{key}"
        )])
    keyboard.append([InlineKeyboardButton("🗑 Удалить чат", callback_data="show_delete")])
    await update.message.reply_text("💬 Твои чаты:", reply_markup=InlineKeyboardMarkup(keyboard))

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    topics = "\n".join([f"• {t}" for t in data["learned_topics"][-10:]]) or "Пока ничего"
    current = data["chats"][data["current_chat"]]["name"]
    await update.message.reply_text(
        f"🧠 Память:\n\n💬 Чат: {current}\n📁 Чатов: {len(data['chats'])}\n\n📚 Изученные темы:\n{topics}",
        reply_markup=main_keyboard()
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    data["chats"][data["current_chat"]]["history"] = []
    save_data(data)
    await update.message.reply_text("🗑 История очищена!", reply_markup=main_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Что я умею:\n\n"
        "💻 *Код на любом языке* — пришлю файл\n"
        "🔍 *Изучить тему* — объясню понятно\n"
        "💬 *Несколько чатов* — переключайся между темами\n"
        "🧠 *Память* — помню всё что изучали\n\n"
        "Примеры:\n"
        "• _Напиши калькулятор на Python_\n"
        "• _Создай сайт-визитку на HTML_\n"
        "• _Объясни как работает интернет_\n"
        "• _Напиши игру змейка на C++_",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()

    if query.data.startswith("switch_"):
        key = query.data.replace("switch_", "")
        if key in data["chats"]:
            data["current_chat"] = key
            save_data(data)
            await query.edit_message_text(f"✅ Переключился на: **{data['chats'][key]['name']}**")

    elif query.data == "show_delete":
        keyboard = [[InlineKeyboardButton(f"🗑 {chat['name']}", callback_data=f"delete_{key}")]
                    for key, chat in data["chats"].items() if key != "default"]
        if not keyboard:
            await query.edit_message_text("❌ Нет чатов для удаления")
        else:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("delete_"):
        key = query.data.replace("delete_", "")
        if key in data["chats"]:
            name = data["chats"][key]["name"]
            del data["chats"][key]
            if data["current_chat"] == key:
                data["current_chat"] = list(data["chats"].keys())[0]
            save_data(data)
            await query.edit_message_text(f"🗑 Чат **{name}** удалён!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "💬 Новый чат":
        await new_chat_cmd(update, context); return
    if text == "📂 Мои чаты":
        await list_chats_cmd(update, context); return
    if text == "🧠 Память":
        await memory_cmd(update, context); return
    if text == "🗑 Очистить чат":
        await clear_cmd(update, context); return
    if text == "❓ Помощь":
        await help_cmd(update, context); return

    if context.user_data.get("waiting_chat_name"):
        context.user_data["waiting_chat_name"] = False
        data = load_data()
        key = f"chat_{int(datetime.now().timestamp())}"
        data["chats"][key] = {"name": text, "history": [], "created": datetime.now().strftime("%d.%m %H:%M")}
        data["current_chat"] = key
        save_data(data)
        await update.message.reply_text(f"✅ Новый чат: **{text}**", reply_markup=main_keyboard())
        return

    data = load_data()
    asyncio.create_task(process_background(context.application, chat_id, text, data))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_chat_cmd))
    app.add_handler(CommandHandler("chats", list_chats_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
