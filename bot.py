import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
import httpx

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# ====== НАСТРОЙКИ ======
TELEGRAM_TOKEN = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GROQ_API_KEY = "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"
MEMORY_FILE = "memory.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== ПАМЯТЬ ======
def load_memory():
    if Path(MEMORY_FILE).exists():
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "profile": {
            "style": "объяснять просто, без терминов, коротко и по делу",
            "learned_topics": []
        },
        "history": []
    }

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def add_to_history(memory, role, text):
    memory["history"].append({
        "role": role,
        "text": text[:400],
        "time": datetime.now().strftime("%d.%m %H:%M")
    })
    if len(memory["history"]) > 50:
        memory["history"] = memory["history"][-50:]

def build_context(memory):
    recent = memory["history"][-8:]
    history_text = "\n".join([f"{m['role']}: {m['text']}" for m in recent])
    topics = ", ".join(memory["profile"]["learned_topics"][-10:]) or "пока ничего"
    return f"""Ты персональный AI-агент. Отвечай просто и по делу, без сложных терминов.
Изученные темы пользователя: {topics}
История разговора:
{history_text}
Если задача на код — пиши полный рабочий код. Если просят объяснить — объясняй как другу с примерами."""

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
            logger.info(f"Groq response status: {r.status_code}")
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

async def process_background(app, chat_id, text, memory):
    try:
        context = build_context(memory)
        await app.bot.send_message(chat_id, "⚙️ Работаю... Занимайся своими делами!")

        result = await ask_groq(text, context)

        if result:
            add_to_history(memory, "Пользователь", text)
            add_to_history(memory, "Агент", result[:300])

            if any(w in text.lower() for w in ["изучи", "расскажи", "объясни", "что такое"]):
                topic = text[:50]
                if topic not in memory["profile"]["learned_topics"]:
                    memory["profile"]["learned_topics"].append(topic)

            save_memory(memory)

            header = "✅ Готово!\n\n"
            full = header + result

            if len(full) > 4096:
                await app.bot.send_message(chat_id, "✅ Готово! Ответ большой, отправляю частями:")
                for i, chunk in enumerate([result[i:i+4000] for i in range(0, len(result), 4000)], 1):
                    await app.bot.send_message(chat_id, f"Часть {i}:\n{chunk}")
            else:
                await app.bot.send_message(chat_id, full)
        else:
            await app.bot.send_message(chat_id, "❌ Groq не ответил. Попробуй ещё раз через минуту.")

    except Exception as e:
        logger.error(f"Background error: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой персональный AI-агент.\n\n"
        "🔍 Изучаю темы и объясняю понятно\n"
        "💻 Пишу код и приложения\n"
        "🧠 Помню всю нашу историю\n"
        "📲 Работаю в фоне пока ты занят\n\n"
        "Просто напиши что нужно!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    memory = load_memory()
    asyncio.create_task(process_background(context.application, chat_id, text, memory))

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = load_memory()
    topics = "\n".join([f"• {t}" for t in memory["profile"]["learned_topics"][-10:]]) or "Пока ничего"
    await update.message.reply_text(
        f"🧠 Что я помню:\n\n📚 Изученные темы:\n{topics}\n\n"
        f"💬 Сообщений в истории: {len(memory['history'])}"
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = load_memory()
    memory["history"] = []
    save_memory(memory)
    await update.message.reply_text("🗑 История очищена!")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
