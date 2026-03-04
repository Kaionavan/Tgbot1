import os
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai
from openai import OpenAI

# ====== НАСТРОЙКИ ======
TELEGRAM_TOKEN = "8634579942:AAFVXcQCblXT5pjjx1Pl5fTOigBg4P7_dZ8"
GEMINI_API_KEY = "AIzaSyD21rIGQxhzh6HXvb05Tkc5SYLBsFVn5II"
DEEPSEEK_API_KEY = "sk-5c112016a71c444e88ea825e3f8c7d4f"
MEMORY_FILE = "memory.json"

# ====== ЛОГИ ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== ИНИЦИАЛИЗАЦИЯ AI ======
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.0-flash")

deepseek = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# ====== ПАМЯТЬ ======
def load_memory():
    if Path(MEMORY_FILE).exists():
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "profile": {
            "name": "",
            "style": "объяснять просто, без терминов, коротко и по делу",
            "goals": [],
            "learned_topics": []
        },
        "history": [],
        "projects": []
    }

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def add_to_history(memory, role, text):
    memory["history"].append({
        "role": role,
        "text": text[:500],  # обрезаем длинные сообщения
        "time": datetime.now().strftime("%d.%m.%Y %H:%M")
    })
    # Храним последние 50 сообщений
    if len(memory["history"]) > 50:
        memory["history"] = memory["history"][-50:]

def build_context(memory):
    profile = memory["profile"]
    recent = memory["history"][-10:]  # последние 10 сообщений

    history_text = "\n".join([
        f"{m['role']}: {m['text']}" for m in recent
    ])

    topics = ", ".join(profile["learned_topics"]) if profile["learned_topics"] else "пока ничего"
    goals = ", ".join(profile["goals"]) if profile["goals"] else "не указаны"

    return f"""Ты — персональный AI-агент. Вот что ты знаешь о пользователе:

Стиль общения: {profile['style']}
Цели пользователя: {goals}
Изученные темы: {topics}

Последние сообщения:
{history_text}

Правила:
- Отвечай коротко и по делу
- Пиши простым языком, без сложных терминов
- Если задача на код — пиши полный рабочий код
- Если просят объяснить — объясняй как другу, с примерами
- Помни контекст разговора, не переспрашивай очевидное
- Если понял к чему ведёт пользователь — сразу делай, не жди уточнений"""

def is_code_task(text):
    keywords = ["создай", "напиши", "сделай", "код", "приложение", "скрипт", 
                "программу", "бот", "сайт", "функцию", "класс", "напиши код",
                "create", "write", "app", "script", "program"]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)

async def ask_gemini(prompt, context):
    try:
        full_prompt = f"{context}\n\nПользователь: {prompt}"
        response = gemini.generate_content(full_prompt)
        return response.text
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return None

async def ask_deepseek(prompt, context):
    try:
        response = deepseek.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": context},
                {"role": "user", "content": prompt}
            ],
            max_tokens=8000
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return None

async def process_task_background(app, chat_id, text, memory):
    """Фоновая обработка задачи"""
    try:
        context = build_context(memory)

        await app.bot.send_message(chat_id, "⚙️ Работаю в фоне... Можешь заниматься своими делами!")

        if is_code_task(text):
            # Для кода используем DeepSeek
            result = await ask_deepseek(text, context)
            ai_used = "DeepSeek"
        else:
            # Для объяснений и учёбы — Gemini
            result = await ask_gemini(text, context)
            ai_used = "Gemini"

        if not result:
            # Fallback на другой AI
            if is_code_task(text):
                result = await ask_gemini(text, context)
                ai_used = "Gemini (резерв)"
            else:
                result = await ask_deepseek(text, context)
                ai_used = "DeepSeek (резерв)"

        if result:
            # Сохраняем в историю
            add_to_history(memory, "Пользователь", text)
            add_to_history(memory, "Агент", result[:300])

            # Обновляем изученные темы
            if any(w in text.lower() for w in ["изучи", "расскажи", "объясни", "что такое", "как работает"]):
                topic = text[:50]
                if topic not in memory["profile"]["learned_topics"]:
                    memory["profile"]["learned_topics"].append(topic)

            save_memory(memory)

            # Отправляем результат
            header = f"✅ Готово! (использовал {ai_used})\n\n"

            # Telegram ограничение 4096 символов
            full_message = header + result
            if len(full_message) > 4096:
                # Отправляем частями
                await app.bot.send_message(chat_id, header + "Ответ большой, отправляю частями:")
                chunks = [result[i:i+4000] for i in range(0, len(result), 4000)]
                for i, chunk in enumerate(chunks, 1):
                    await app.bot.send_message(chat_id, f"Часть {i}:\n{chunk}")
            else:
                await app.bot.send_message(chat_id, full_message)
        else:
            await app.bot.send_message(chat_id, "❌ Что-то пошло не так с AI. Попробуй ещё раз.")

    except Exception as e:
        logger.error(f"Background task error: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {str(e)}")

# ====== ОБРАБОТЧИКИ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = load_memory()
    await update.message.reply_text(
        "👋 Привет! Я твой персональный AI-агент.\n\n"
        "Что умею:\n"
        "🔍 Изучаю темы и объясняю понятно\n"
        "💻 Пишу код и приложения\n"
        "🧠 Помню всё о тебе и нашу историю\n"
        "📲 Работаю в фоне пока ты занят\n\n"
        "Просто напиши что нужно сделать!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    memory = load_memory()

    # Быстрые ответы на простые вопросы
    simple_keywords = ["привет", "как дела", "что умеешь", "помощь", "help"]
    if any(k in text.lower() for k in simple_keywords) and len(text) < 30:
        context_text = build_context(memory)
        result = await ask_gemini(text, context_text)
        if result:
            add_to_history(memory, "Пользователь", text)
            add_to_history(memory, "Агент", result[:300])
            save_memory(memory)
            await update.message.reply_text(result[:4096])
        return

    # Всё остальное — в фоне
    asyncio.create_task(
        process_task_background(context.application, chat_id, text, memory)
    )

async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать что агент помнит"""
    memory = load_memory()
    profile = memory["profile"]
    topics = "\n".join([f"• {t}" for t in profile["learned_topics"][-10:]]) or "Пока ничего"
    history_count = len(memory["history"])

    await update.message.reply_text(
        f"🧠 Вот что я помню о тебе:\n\n"
        f"📚 Изученные темы:\n{topics}\n\n"
        f"💬 Сообщений в истории: {history_count}\n"
        f"🎯 Стиль общения: {profile['style']}"
    )

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить историю"""
    memory = load_memory()
    memory["history"] = []
    save_memory(memory)
    await update.message.reply_text("🗑 История очищена! Профиль сохранён.")

# ====== ЗАПУСК ======
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
