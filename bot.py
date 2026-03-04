import json
import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

# ====== НАСТРОЙКИ ======
TELEGRAM_TOKEN = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GROQ_API_KEY = "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"
DATA_FILE = "data.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== ДАННЫЕ ======
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
    chat_id = data["current_chat"]
    return data["chats"][chat_id]["history"]

def add_message(data, role, text):
    history = get_current_history(data)
    history.append({
        "role": role,
        "text": text[:500],
        "time": datetime.now().strftime("%d.%m %H:%M")
    })
    if len(history) > 50:
        data["chats"][data["current_chat"]]["history"] = history[-50:]

def build_context(data):
    history = get_current_history(data)[-8:]
    history_text = "\n".join([f"{m['role']}: {m['text']}" for m in history])
    topics = ", ".join(data["learned_topics"][-10:]) or "пока ничего"
    chat_name = data["chats"][data["current_chat"]]["name"]
    return f"""Ты персональный AI-агент. Отвечай просто и по делу, без лишних терминов.
Текущий чат: {chat_name}
Изученные темы: {topics}
История:
{history_text}
Правила:
- Если просят написать код — пиши ПОЛНЫЙ рабочий код
- Объясняй как другу, с примерами
- Помни контекст разговора"""

def extract_code(text):
    """Извлекает код из ответа AI"""
    patterns = [
        r'```python\n(.*?)```',
        r'```py\n(.*?)```',
        r'```\n(.*?)```',
        r'```python(.*?)```',
        r'```(.*?)```',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return matches[0].strip()
    return None

def detect_file_type(prompt, code):
    """Определяет язык по запросу и коду"""
    p = prompt.lower()
    if 'html' in p or 'сайт' in p or 'веб' in p: return 'html'
    if 'css' in p: return 'css'
    if 'javascript' in p or ' js ' in p: return 'js'
    if 'typescript' in p: return 'ts'
    if 'c++' in p or 'cpp' in p or 'си++' in p: return 'cpp'
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
        if '#include' in code or 'cout <<' in code: return 'cpp'
        if 'using System' in code: return 'cs'
        if 'public class' in code and 'System.out' in code: return 'java'
        if 'fun main' in code: return 'kt'
        if 'console.log' in code or 'const ' in code: return 'js'
        if '<html' in code or '<!DOCTYPE' in code: return 'html'
    return 'py'

# ====== AI ======
async def ask_groq(prompt, context):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
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

def is_code_task(text):
    keywords = ["создай", "напиши", "сделай", "код", "приложение", "скрипт",
                "программу", "бот", "сайт", "функцию", "create", "write", "app",
                "calculator", "калькулятор", "игру", "game"]
    return any(k in text.lower() for k in keywords)

# ====== ФОНОВАЯ ОБРАБОТКА ======
async def process_background(app, chat_id, text, data):
    try:
        context = build_context(data)
        await app.bot.send_message(chat_id, "⚙️ Работаю... Занимайся своими делами!")

        result = await ask_groq(text, context)

        if not result:
            await app.bot.send_message(chat_id, "❌ AI не ответил. Попробуй ещё раз.")
            return

        add_message(data, "Пользователь", text)
        add_message(data, "Агент", result[:400])

        # Сохраняем изученные темы
        if any(w in text.lower() for w in ["изучи", "расскажи", "объясни", "что такое", "как работает"]):
            topic = text[:60]
            if topic not in data["learned_topics"]:
                data["learned_topics"].append(topic)

        save_data(data)

        # Если задача на код — извлекаем и отправляем файл
        if is_code_task(text):
            code = extract_code(result)
            if code:
                ext = detect_file_type(text, code)
                filename = f"code.{ext}"

                # Отправляем текст объяснения (без кода)
                explanation = re.sub(r'```.*?```', '📎 (код в файле ниже)', result, flags=re.DOTALL).strip()
                if explanation:
                    chunks = [explanation[i:i+4000] for i in range(0, len(explanation), 4000)]
                    for chunk in chunks:
                        await app.bot.send_message(chat_id, f"✅ Готово!\n\n{chunk}")

                # Отправляем файл
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(code)
                with open(filename, 'rb') as f:
                    await app.bot.send_document(
                        chat_id,
                        document=f,
                        filename=filename,
                        caption=f"📁 Готовый файл `{filename}`"
                    )
                os.remove(filename)
                return

        # Обычный текстовый ответ
        header = "✅ Готово!\n\n"
        full = header + result
        if len(full) > 4096:
            await app.bot.send_message(chat_id, "✅ Готово! Ответ большой, отправляю частями:")
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
        "🔍 Изучаю темы и объясняю понятно\n"
        "💻 Пишу код и отправляю готовые файлы\n"
        "🧠 Помню историю каждого чата\n"
        "📲 Работаю в фоне\n\n"
        "Команды:\n"
        "/new — новый чат\n"
        "/chats — список чатов\n"
        "/delete — удалить чат\n"
        "/memory — что помню\n"
        "/clear — очистить текущий чат\n\n"
        "Просто напиши что нужно!"
    )

async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    name = " ".join(args) if args else f"Чат {datetime.now().strftime('%d.%m %H:%M')}"
    data = load_data()
    chat_key = f"chat_{int(datetime.now().timestamp())}"
    data["chats"][chat_key] = {
        "name": name,
        "history": [],
        "created": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    data["current_chat"] = chat_key
    save_data(data)
    await update.message.reply_text(f"✅ Новый чат создан: **{name}**\nТеперь работаем в нём!")

async def list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    current = data["current_chat"]
    keyboard = []
    for key, chat in data["chats"].items():
        mark = "✅ " if key == current else ""
        keyboard.append([InlineKeyboardButton(
            f"{mark}{chat['name']} ({len(chat['history'])} сообщ.)",
            callback_data=f"switch_{key}"
        )])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💬 Твои чаты (нажми чтобы переключиться):", reply_markup=reply_markup)

async def delete_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if len(data["chats"]) <= 1:
        await update.message.reply_text("❌ Нельзя удалить последний чат!")
        return
    current = data["current_chat"]
    keyboard = []
    for key, chat in data["chats"].items():
        if key != "default":
            keyboard.append([InlineKeyboardButton(
                f"🗑 {chat['name']}",
                callback_data=f"delete_{key}"
            )])
    if not keyboard:
        await update.message.reply_text("❌ Нет чатов для удаления!")
        return
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Какой чат удалить?", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()

    if query.data.startswith("switch_"):
        key = query.data.replace("switch_", "")
        if key in data["chats"]:
            data["current_chat"] = key
            save_data(data)
            name = data["chats"][key]["name"]
            await query.edit_message_text(f"✅ Переключился на чат: **{name}**")

    elif query.data.startswith("delete_"):
        key = query.data.replace("delete_", "")
        if key in data["chats"]:
            name = data["chats"][key]["name"]
            del data["chats"][key]
            if data["current_chat"] == key:
                data["current_chat"] = list(data["chats"].keys())[0]
            save_data(data)
            await query.edit_message_text(f"🗑 Чат **{name}** удалён!")

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    topics = "\n".join([f"• {t}" for t in data["learned_topics"][-10:]]) or "Пока ничего"
    current = data["chats"][data["current_chat"]]["name"]
    total_chats = len(data["chats"])
    await update.message.reply_text(
        f"🧠 Моя память:\n\n"
        f"💬 Текущий чат: {current}\n"
        f"📁 Всего чатов: {total_chats}\n\n"
        f"📚 Изученные темы:\n{topics}"
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    data["chats"][data["current_chat"]]["history"] = []
    save_data(data)
    await update.message.reply_text("🗑 История текущего чата очищена!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    data = load_data()
    asyncio.create_task(process_background(context.application, chat_id, text, data))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_chat))
    app.add_handler(CommandHandler("chats", list_chats))
    app.add_handler(CommandHandler("delete", delete_chat))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
