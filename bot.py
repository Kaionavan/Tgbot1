import os
import json
import asyncio
import logging
import tempfile
import base64
import re
from datetime import datetime
from pathlib import Path

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes, CallbackQueryHandler
)

# ====== НАСТРОЙКИ ======
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не задан! Добавь в Railway Variables.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ====== МОДЕЛИ ======
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-2-9b-it:free",
]
COHERE_MODEL = "command-r-plus"

# ====== ПАМЯТЬ ======

def load_memory(user_id: int) -> dict:
    path = f"memory_{user_id}.json"
    default = {
        "profile": {
            "learned_topics": [],
            "quality_notes": [],
            "preferred_style": "",
            "feedback_history": []
        },
        "history": [],
        "stats": {
            "messages": 0, "codes_generated": 0,
            "images_analyzed": 0, "voices_processed": 0,
            "searches_done": 0, "positive_feedback": 0, "negative_feedback": 0
        }
    }
    if Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in default:
                if k not in data:
                    data[k] = default[k]
            for k in default["profile"]:
                if k not in data["profile"]:
                    data["profile"][k] = default["profile"][k]
            return data
        except:
            pass
    return default

def save_memory(memory: dict, user_id: int):
    try:
        with open(f"memory_{user_id}.json", "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save error: {e}")

def add_to_history(memory: dict, role: str, text: str):
    memory["history"].append({
        "role": role, "text": text[:600],
        "time": datetime.now().strftime("%d.%m %H:%M")
    })
    if len(memory["history"]) > 80:
        memory["history"] = memory["history"][-80:]

# ====== САМООБУЧЕНИЕ ======

def build_context(memory: dict) -> str:
    profile = memory["profile"]
    recent = memory["history"][-12:]
    history_text = "\n".join([f"{m['role']}: {m['text']}" for m in recent])
    topics = ", ".join(profile["learned_topics"][-20:]) or "пока ничего"
    notes = "\n".join([f"• {n}" for n in profile.get("quality_notes", [])[-8:]]) or "нет"
    style = profile.get("preferred_style", "") or "дружелюбный, простой"
    s = memory.get("stats", {})
    pos, neg = s.get("positive_feedback", 0), s.get("negative_feedback", 0)
    total = pos + neg
    quality = f"{int(pos/total*100)}%" if total > 0 else "нет данных"

    return f"""Ты персональный AI-агент. Умный, быстрый, полезный.

СТИЛЬ ОБЩЕНИЯ: {style}
КАК УЛУЧШИТЬ ОТВЕТЫ:\n{notes}
ИЗУЧЕННЫЕ ТЕМЫ: {topics}
КАЧЕСТВО: {quality} ({pos} хороших / {neg} плохих)

ИСТОРИЯ:\n{history_text}

ПРАВИЛА:
- Код всегда полный и рабочий
- Объясняй как другу — просто и понятно
- Отвечай на том же языке на котором спрашивают"""

async def auto_improve(memory: dict, user_msg: str, bot_resp: str, user_id: int):
    if memory["stats"].get("messages", 0) % 10 != 0:
        return
    prompt = f"""Проанализируй диалог и дай рекомендации.
Последние сообщения:
{chr(10).join([f"{m['role']}: {m['text']}" for m in memory['history'][-20:]])}

Ответь ТОЛЬКО JSON без markdown:
{{"quality_note": "рекомендация до 100 символов", "preferred_style": "стиль до 80 символов"}}"""
    try:
        result, _ = await ask_ai(prompt, system="Ты аналитик качества AI ответов. Отвечай только JSON.")
        if result:
            clean = result.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            if data.get("quality_note"):
                notes = memory["profile"].get("quality_notes", [])
                notes.append(data["quality_note"])
                memory["profile"]["quality_notes"] = notes[-15:]
            if data.get("preferred_style"):
                memory["profile"]["preferred_style"] = data["preferred_style"]
            save_memory(memory, user_id)
    except Exception as e:
        logger.debug(f"Auto-improve skipped: {e}")

# ====== AI ПРОВАЙДЕРЫ ======

async def ask_groq(prompt: str, system: str) -> tuple[str | None, str]:
    if not GROQ_API_KEY:
        return None, ""
    for model in GROQ_MODELS:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 4000
                    }
                )
                data = r.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"], f"Groq/{model.split('-')[0]+'-'+model.split('-')[1]}"
            err = data.get("error", {})
            logger.warning(f"Groq {model}: {err.get('message','')[:80]}")
        except Exception as e:
            logger.warning(f"Groq {model}: {e}")
    return None, ""

async def ask_openrouter(prompt: str, system: str) -> tuple[str | None, str]:
    if not OPENROUTER_API_KEY:
        return None, ""
    models = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat-v3-0324:free",
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-2-9b-it:free",
        "microsoft/phi-3-mini-128k-instruct:free",
    ]
    for model in models:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://github.com/Kaionavan/Tgbot1",
                        "X-Title": "AgentBot",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 4000,
                        "temperature": 0.7
                    }
                )
            data = r.json()
            if "choices" in data and data["choices"]:
                text = data["choices"][0]["message"].get("content", "")
                if text and len(text.strip()) > 5:
                    short = model.split("/")[-1].replace(":free", "")[:20]
                    return text, f"OpenRouter/{short}"
            err = data.get("error", {})
            logger.warning(f"OpenRouter {model}: {r.status_code} {err.get('message','')[:80]}")
        except Exception as e:
            logger.warning(f"OpenRouter {model}: {e}")
    return None, ""

async def ask_cohere(prompt: str, system: str) -> tuple[str | None, str]:
    if not COHERE_API_KEY:
        return None, ""
    # Пробуем v2 API
    for model in ["command-r-plus", "command-r", "command"]:
        try:
            async with httpx.AsyncClient(timeout=40) as client:
                r = await client.post(
                    "https://api.cohere.com/v2/chat",
                    headers={
                        "Authorization": f"Bearer {COHERE_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 4000
                    }
                )
            data = r.json()
            # v2 формат ответа
            if "message" in data:
                content = data["message"].get("content", [])
                if isinstance(content, list) and content:
                    text = content[0].get("text", "")
                    if text:
                        return text, f"Cohere/{model}"
                elif isinstance(content, str) and content:
                    return content, f"Cohere/{model}"
            # Альтернативный формат
            if "text" in data:
                return data["text"], f"Cohere/{model}"
            logger.warning(f"Cohere {model}: {r.status_code} {str(data)[:100]}")
        except Exception as e:
            logger.warning(f"Cohere {model}: {e}")
    return None, ""

async def ask_deepseek(prompt: str, system: str) -> tuple[str | None, str]:
    if not DEEPSEEK_API_KEY:
        return None, ""
    for model in ["deepseek-chat", "deepseek-reasoner"]:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 8000
                    }
                )
            data = r.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"], f"DeepSeek/{model.replace('deepseek-','')}"
            err = data.get("error", {})
            logger.warning(f"DeepSeek {model}: {err.get('message','')[:80]}")
        except Exception as e:
            logger.warning(f"DeepSeek {model}: {e}")
    return None, ""


    if not GEMINI_API_KEY:
        return None, ""
    for model in GEMINI_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}]}
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                data = r.json()
            if "candidates" in data and data["candidates"]:
                return data["candidates"][0]["content"]["parts"][0]["text"], f"Gemini/{model.replace('gemini-','')}"
            err = data.get("error", {})
            logger.warning(f"Gemini {model}: {err.get('code')} {err.get('message','')[:60]}")
        except Exception as e:
            logger.warning(f"Gemini {model}: {e}")
    return None, ""

async def ask_gemini_vision(prompt: str, system: str, image_data: bytes, mime_type: str) -> tuple[str | None, str]:
    """Только Gemini умеет анализировать изображения"""
    if not GEMINI_API_KEY:
        return None, ""
    for model in GEMINI_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            img_b64 = base64.b64encode(image_data).decode()
            payload = {"contents": [{"parts": [
                {"text": f"{system}\n\n{prompt}"},
                {"inline_data": {"mime_type": mime_type, "data": img_b64}}
            ]}]}
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                data = r.json()
            if "candidates" in data and data["candidates"]:
                return data["candidates"][0]["content"]["parts"][0]["text"], f"Gemini/{model.replace('gemini-','')}"
            err = data.get("error", {})
            logger.warning(f"Gemini vision {model}: {err.get('message','')[:60]}")
        except Exception as e:
            logger.warning(f"Gemini vision {model}: {e}")
    return None, ""

async def ask_gemini_audio(prompt: str, system: str, audio_data: bytes) -> tuple[str | None, str]:
    """Только Gemini умеет обрабатывать аудио"""
    if not GEMINI_API_KEY:
        return None, ""
    for model in GEMINI_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            aud_b64 = base64.b64encode(audio_data).decode()
            payload = {"contents": [{"parts": [
                {"text": "Транскрибируй это аудио на русском, затем ответь на сказанное."},
                {"inline_data": {"mime_type": "audio/ogg", "data": aud_b64}}
            ]}]}
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                data = r.json()
            if "candidates" in data and data["candidates"]:
                return data["candidates"][0]["content"]["parts"][0]["text"], f"Gemini/{model.replace('gemini-','')}"
        except Exception as e:
            logger.warning(f"Gemini audio {model}: {e}")
    return None, ""

async def ask_ai(prompt: str, system: str = "") -> tuple[str | None, str]:
    """Умная очередь: Groq → DeepSeek → OpenRouter → Cohere → Gemini"""
    if not system:
        system = "Ты полезный AI-агент. Отвечай на русском если вопрос на русском."
    result, model = await ask_groq(prompt, system)
    if result: return result, model
    result, model = await ask_deepseek(prompt, system)
    if result: return result, model
    result, model = await ask_openrouter(prompt, system)
    if result: return result, model
    result, model = await ask_cohere(prompt, system)
    if result: return result, model
    result, model = await ask_gemini_text(prompt, system)
    if result: return result, model
    return None, "none"

# ====== WEB SEARCH ======

async def web_search(query: str) -> str:
    try:
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://api.duckduckgo.com/", params=params)
            data = r.json()
        results = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"][:500])
        for t in data.get("RelatedTopics", [])[:5]:
            if isinstance(t, dict) and t.get("Text"):
                results.append(t["Text"][:200])
        if results:
            return "Поиск:\n" + "\n".join(results[:5])
        return "Поиск не дал результатов, отвечу из своих знаний."
    except:
        return "Поиск недоступен."

# ====== УТИЛИТЫ ======

def is_code_task(text: str) -> bool:
    kw = ["создай","напиши","сделай","код","скрипт","программу","бот","сайт",
          "функцию","класс","create","write","code","исправь","fix","debug","починить","приложение"]
    return any(k in text.lower() for k in kw)

def is_search_task(text: str) -> bool:
    kw = ["найди","поищи","загугли","актуальн","новост","последн","сейчас","search","найти"]
    return any(k in text.lower() for k in kw)

def is_deep_study(text: str) -> bool:
    return bool(re.match(r'^(изучи|изучить|исследуй)\s+\S', text.strip(), re.IGNORECASE))

def detect_lang_ext(text: str) -> tuple[str, str]:
    t = text.lower()
    if "python" in t or "def " in text or "import " in text: return "python", ".py"
    if "javascript" in t or "const " in text or "function " in text: return "javascript", ".js"
    if "html" in t or "<html" in t: return "html", ".html"
    if "css" in t: return "css", ".css"
    if "sql" in t: return "sql", ".sql"
    if "bash" in t or "#!/bin" in text: return "bash", ".sh"
    if "typescript" in t: return "typescript", ".ts"
    return "python", ".py"

def extract_code(text: str) -> list[str]:
    blocks = re.findall(r'```[\w]*\n?(.*?)```', text, re.DOTALL)
    return [b.strip() for b in blocks if len(b.strip()) > 30]

async def send_chunks(app, chat_id: int, text: str, reply_markup=None):
    if len(text) <= 4096:
        try:
            await app.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=reply_markup)
        except:
            await app.bot.send_message(chat_id, text, reply_markup=reply_markup)
        return
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for i, chunk in enumerate(chunks, 1):
        try:
            await app.bot.send_message(chat_id, f"*{i}/{len(chunks)}:*\n{chunk}", parse_mode="Markdown")
        except:
            await app.bot.send_message(chat_id, chunk)
    if reply_markup:
        await app.bot.send_message(chat_id, "Оцени ответ:", reply_markup=reply_markup)

# ====== ГЛУБОКОЕ ИЗУЧЕНИЕ ======

async def deep_research(topic: str, app, chat_id: int, memory: dict, user_id: int):
    await app.bot.send_message(chat_id, f"🔬 Изучаю: *{topic}*\n~1-2 минуты...", parse_mode="Markdown")
    await app.bot.send_message(chat_id, "📚 1/4 Основы...")
    s1 = await web_search(topic)
    await app.bot.send_message(chat_id, "⚙️ 2/4 Практика...")
    s2 = await web_search(f"{topic} примеры применение")
    await app.bot.send_message(chat_id, "📰 3/4 Актуальность...")
    s3 = await web_search(f"{topic} 2024 2025")
    await app.bot.send_message(chat_id, "🧠 4/4 Синтез...")

    prompt = f"""Составь полный обучающий материал по теме "{topic}".

Данные из поиска:
{s1}
{s2}
{s3}

Структура:
1. Что это (простыми словами)
2. Зачем нужно и где применяется
3. Ключевые концепции (3-5 штук)
4. Практический пример
5. С чего начать
6. Полезные ресурсы"""

    result, model = await ask_ai(prompt, build_context(memory))
    if result:
        if topic not in memory["profile"]["learned_topics"]:
            memory["profile"]["learned_topics"].append(topic)
        add_to_history(memory, "Изучена тема", topic)
        memory["stats"]["searches_done"] = memory["stats"].get("searches_done", 0) + 3
        save_memory(memory, user_id)
        await send_chunks(app, chat_id, f"✅ *'{topic}'* изучена! _{model}_\n\n{result}")
    else:
        await app.bot.send_message(chat_id, "❌ Все AI не ответили. Попробуй позже.")

# ====== ГЛАВНАЯ ОБРАБОТКА ======

async def process_background(app, chat_id: int, text: str, memory: dict, user_id: int,
                               image_data: bytes = None, mime_type: str = None,
                               audio_data: bytes = None):
    try:
        memory["stats"]["messages"] = memory["stats"].get("messages", 0) + 1

        # Глубокое изучение
        if is_deep_study(text) and not image_data and not audio_data:
            topic = re.sub(r'^(изучи|изучить|исследуй)\s+', '', text.strip(), flags=re.IGNORECASE)
            await deep_research(topic, app, chat_id, memory, user_id)
            return

        await app.bot.send_message(chat_id, "⚙️ Работаю...")
        system = build_context(memory)

        # Поиск если нужен
        search_ctx = ""
        if is_search_task(text) and not image_data and not audio_data:
            search_ctx = "\n\n" + await web_search(text)
            memory["stats"]["searches_done"] = memory["stats"].get("searches_done", 0) + 1

        # Выбор режима
        if image_data:
            # Изображения — только Gemini
            result, model = await ask_gemini_vision(
                text or "Подробно опиши что видишь", system, image_data, mime_type or "image/jpeg"
            )
            if not result:
                result = "❌ Анализ изображений требует Gemini API. Добавь рабочий GEMINI_API_KEY."
                model = "none"
            memory["stats"]["images_analyzed"] = memory["stats"].get("images_analyzed", 0) + 1
            icon = "🖼"

        elif audio_data:
            # Аудио — только Gemini
            result, model = await ask_gemini_audio("", system, audio_data)
            if not result:
                result = "❌ Голосовые требуют Gemini API. Добавь рабочий GEMINI_API_KEY."
                model = "none"
            memory["stats"]["voices_processed"] = memory["stats"].get("voices_processed", 0) + 1
            icon = "🎤"

        else:
            result, model = await ask_ai(text + search_ctx, system)
            if is_code_task(text):
                memory["stats"]["codes_generated"] = memory["stats"].get("codes_generated", 0) + 1
            icon = "💻" if is_code_task(text) else "💬"

        if not result:
            await app.bot.send_message(
                chat_id,
                "❌ Все AI временно недоступны.\n\n"
                "Проверь что добавил ключи в Railway Variables:\n"
                "• GROQ_API_KEY\n• OPENROUTER_API_KEY\n• COHERE_API_KEY"
            )
            return

        add_to_history(memory, "Пользователь", text or "[медиа]")
        add_to_history(memory, "Агент", result[:500])
        asyncio.create_task(auto_improve(memory, text, result, user_id))
        save_memory(memory, user_id)

        short_model = model.split("/")[-1] if "/" in model else model
        keyboard = [[
            InlineKeyboardButton("👍", callback_data=f"fb_good_{user_id}"),
            InlineKeyboardButton("👎", callback_data=f"fb_bad_{user_id}")
        ]]
        markup = InlineKeyboardMarkup(keyboard)

        await send_chunks(app, chat_id, f"{icon} _{short_model}_\n\n{result}", reply_markup=markup)

        # Код → файл
        if is_code_task(text) and not image_data:
            blocks = extract_code(result)
            if blocks:
                _, ext = detect_lang_ext(result + text)
                fname = f"code_{datetime.now().strftime('%H%M%S')}{ext}"
                with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False, encoding='utf-8') as f:
                    f.write("\n\n".join(blocks))
                    tmp = f.name
                try:
                    with open(tmp, 'rb') as f:
                        await app.bot.send_document(chat_id, f, filename=fname,
                                                    caption=f"📁 `{fname}`", parse_mode="Markdown")
                finally:
                    os.unlink(tmp)

    except Exception as e:
        logger.error(f"Process error: {e}", exc_info=True)
        await app.bot.send_message(chat_id, f"❌ Ошибка: {str(e)[:200]}")

# ====== ХЕНДЛЕРЫ ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Показываем какие AI доступны
    ai_status = []
    ai_status.append(f"{'✅' if GROQ_API_KEY else '❌'} Groq (Llama)")
    ai_status.append(f"{'✅' if DEEPSEEK_API_KEY else '❌'} DeepSeek")
    ai_status.append(f"{'✅' if OPENROUTER_API_KEY else '❌'} OpenRouter")
    ai_status.append(f"{'✅' if COHERE_API_KEY else '❌'} Cohere")
    ai_status.append(f"{'✅' if GEMINI_API_KEY else '❌'} Gemini (резерв)")
    status_text = "\n".join(ai_status)

    kb = [[InlineKeyboardButton("🧠 Память", callback_data="memory"),
           InlineKeyboardButton("📊 Статистика", callback_data="stats")],
          [InlineKeyboardButton("🤖 AI статус", callback_data="ai_status"),
           InlineKeyboardButton("❓ Помощь", callback_data="help")],
          [InlineKeyboardButton("🗑 Очистить", callback_data="clear")]]
    await update.message.reply_text(
        f"👋 Привет! Я твой AI-агент.\n\n"
        f"*AI движки:*\n{status_text}\n\n"
        f"💻 Пишу код → файлом\n"
        f"📸 Анализирую фото\n"
        f"🎤 Понимаю голосовые\n"
        f"🔍 Ищу в интернете\n"
        f"📚 Изучаю темы (*изучи [тема]*)\n"
        f"🧠 Самообучаюсь от оценок 👍/👎",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )

async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Проверяю все AI...")
    results = []

    # Groq
    if GROQ_API_KEY:
        r, m = await ask_groq("Ответь одним словом: работаю", "test")
        results.append(f"{'✅' if r else '❌'} Groq: {m if r else 'не отвечает'}")
    else:
        results.append("⚪ Groq: ключ не задан")

    # OpenRouter
    if OPENROUTER_API_KEY:
        r, m = await ask_openrouter("Ответь одним словом: работаю", "test")
        results.append(f"{'✅' if r else '❌'} OpenRouter: {m if r else 'не отвечает'}")
    else:
        results.append("⚪ OpenRouter: ключ не задан")

    # DeepSeek
    if DEEPSEEK_API_KEY:
        r, m = await ask_deepseek("Ответь одним словом: работаю", "test")
        results.append(f"{'✅' if r else '❌'} DeepSeek: {m if r else 'не отвечает'}")
    else:
        results.append("⚪ DeepSeek: ключ не задан")

    # Cohere
    if COHERE_API_KEY:
        r, m = await ask_cohere("Ответь одним словом: работаю", "test")
        results.append(f"{'✅' if r else '❌'} Cohere: {m if r else 'не отвечает'}")
    else:
        results.append("⚪ Cohere: ключ не задан")

    # Gemini
    if GEMINI_API_KEY:
        r, m = await ask_gemini_text("Ответь одним словом: работаю", "test")
        results.append(f"{'✅' if r else '❌'} Gemini: {m if r else 'не отвечает'}")
    else:
        results.append("⚪ Gemini: ключ не задан")

    await update.message.reply_text("🤖 *Статус AI:*\n\n" + "\n".join(results), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    memory = load_memory(user_id)
    asyncio.create_task(process_background(
        context.application, update.effective_chat.id, update.message.text, memory, user_id
    ))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    memory = load_memory(user_id)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    async with httpx.AsyncClient() as c:
        image_data = (await c.get(file.file_path)).content
    asyncio.create_task(process_background(
        context.application, update.effective_chat.id,
        update.message.caption or "Подробно опиши что видишь",
        memory, user_id, image_data=image_data, mime_type="image/jpeg"
    ))

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    memory = load_memory(user_id)
    doc = update.message.document
    file = await context.bot.get_file(doc.file_id)
    async with httpx.AsyncClient() as c:
        file_data = (await c.get(file.file_path)).content
    mime = doc.mime_type or ""
    name = doc.file_name or ""
    caption = update.message.caption or "Проанализируй файл."
    if mime.startswith("image/"):
        asyncio.create_task(process_background(
            context.application, chat_id, caption, memory, user_id,
            image_data=file_data, mime_type=mime
        ))
    elif mime.startswith("text/") or name.endswith(('.py','.js','.html','.txt','.json','.md','.css','.ts','.sh')):
        content = file_data.decode('utf-8', errors='ignore')
        asyncio.create_task(process_background(
            context.application, chat_id,
            f"{caption}\n\nФайл `{name}`:\n```\n{content[:4000]}\n```",
            memory, user_id
        ))
    else:
        await update.message.reply_text(f"📎 {name}\nПоддерживаю: изображения и текстовые файлы.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    memory = load_memory(user_id)
    await update.message.reply_text("🎤 Обрабатываю голосовое...")
    file = await context.bot.get_file(update.message.voice.file_id)
    async with httpx.AsyncClient() as c:
        audio_data = (await c.get(file.file_path)).content
    asyncio.create_task(process_background(
        context.application, chat_id, "", memory, user_id, audio_data=audio_data
    ))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    memory = load_memory(user_id)
    data = query.data

    if data.startswith("fb_good_"):
        memory["stats"]["positive_feedback"] = memory["stats"].get("positive_feedback", 0) + 1
        memory["profile"]["feedback_history"].append({"type": "good", "time": datetime.now().isoformat()})
        memory["profile"]["feedback_history"] = memory["profile"]["feedback_history"][-50:]
        save_memory(memory, user_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("👍 Понял! Запомнил что этот стиль тебе нравится.")

    elif data.startswith("fb_bad_"):
        memory["stats"]["negative_feedback"] = memory["stats"].get("negative_feedback", 0) + 1
        last_q = memory["history"][-2]["text"][:60] if len(memory["history"]) >= 2 else "неизвестно"
        memory["profile"]["quality_notes"].append(f"Недоволен ответом на: {last_q}")
        memory["profile"]["feedback_history"].append({"type": "bad", "time": datetime.now().isoformat()})
        memory["profile"]["feedback_history"] = memory["profile"]["feedback_history"][-50:]
        save_memory(memory, user_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("👎 Понял, постараюсь лучше. Скажи что было не так?")

    elif data == "ai_status":
        lines = [
            f"{'✅' if GROQ_API_KEY else '❌'} Groq — {'задан' if GROQ_API_KEY else 'нет ключа'}",
            f"{'✅' if OPENROUTER_API_KEY else '❌'} OpenRouter — {'задан' if OPENROUTER_API_KEY else 'нет ключа'}",
            f"{'✅' if COHERE_API_KEY else '❌'} Cohere — {'задан' if COHERE_API_KEY else 'нет ключа'}",
            f"{'✅' if GEMINI_API_KEY else '❌'} Gemini — {'задан' if GEMINI_API_KEY else 'нет ключа'}",
        ]
        await query.edit_message_text(
            "🤖 *AI движки:*\n\n" + "\n".join(lines) +
            "\n\nДля проверки напиши /ping",
            parse_mode="Markdown"
        )

    elif data == "memory":
        topics = "\n".join([f"• {t}" for t in memory["profile"]["learned_topics"][-15:]]) or "Пока ничего"
        notes = "\n".join([f"• {n}" for n in memory["profile"].get("quality_notes", [])[-5:]]) or "Нет данных"
        style = memory["profile"].get("preferred_style", "не определён")
        await query.edit_message_text(
            f"🧠 *Память агента:*\n\n"
            f"🎨 Стиль: _{style}_\n\n"
            f"💡 Заметки:\n{notes}\n\n"
            f"📚 Темы:\n{topics}\n\n"
            f"💬 История: {len(memory['history'])} сообщений",
            parse_mode="Markdown"
        )

    elif data == "stats":
        s = memory.get("stats", {})
        pos, neg = s.get("positive_feedback", 0), s.get("negative_feedback", 0)
        total = pos + neg
        q = f"{int(pos/total*100)}%" if total > 0 else "нет оценок"
        await query.edit_message_text(
            f"📊 *Статистика:*\n\n"
            f"💬 Сообщений: {s.get('messages',0)}\n"
            f"💻 Кодов: {s.get('codes_generated',0)}\n"
            f"📸 Фото: {s.get('images_analyzed',0)}\n"
            f"🎤 Голосовых: {s.get('voices_processed',0)}\n"
            f"🔍 Поисков: {s.get('searches_done',0)}\n\n"
            f"👍 {pos} / 👎 {neg} | ⭐ {q}",
            parse_mode="Markdown"
        )

    elif data == "clear":
        memory["history"] = []
        save_memory(memory, user_id)
        await query.edit_message_text("🗑 История очищена!")

    elif data == "help":
        await query.edit_message_text(
            "*Как пользоваться:*\n\n"
            "• Текст → отвечу\n"
            "• Фото → проанализирую (нужен Gemini)\n"
            "• Голосовое → распознаю (нужен Gemini)\n"
            "• Файл (.py .js .txt...) → прочитаю\n\n"
            "*Спецзапросы:*\n"
            "• _изучи [тема]_ → глубокое исследование\n"
            "• _найди [запрос]_ → поиск в сети\n"
            "• _напиши код..._ → получишь файл\n\n"
            "*Самообучение:*\n"
            "Нажимай 👍/👎 — запоминаю что тебе нравится, каждые 10 сообщений анализирую как стать лучше.\n\n"
            "/ping — проверить все AI\n"
            "/memory /stats /clear",
            parse_mode="Markdown"
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Как пользоваться агентом:*\n\n"
        "Просто напиши любое сообщение!\n\n"
        "📝 *Текст* → отвечу\n"
        "📸 *Фото* → проанализирую\n"
        "🎤 *Голосовое* → распознаю и отвечу\n"
        "📎 *Файл* (.py .js .txt...) → прочитаю\n\n"
        "*Спецзапросы:*\n"
        "• _изучи [тема]_ → глубокое исследование\n"
        "• _найди [запрос]_ → поиск в интернете\n"
        "• _напиши код..._ → получишь файл\n\n"
        "*Самообучение:*\n"
        "Нажимай 👍/👎 после ответов — я учусь и улучшаю стиль каждые 10 сообщений\n\n"
        "*Команды:*\n"
        "/start — главное меню\n"
        "/ping — статус всех AI\n"
        "/memory — что помню\n"
        "/stats — статистика\n"
        "/clear — очистить историю",
        parse_mode="Markdown"
    )


    memory = load_memory(update.effective_user.id)
    topics = "\n".join([f"• {t}" for t in memory["profile"]["learned_topics"][-15:]]) or "Пока ничего"
    await update.message.reply_text(
        f"🧠 *Память:*\n\n📚 Темы:\n{topics}\n\n💬 История: {len(memory['history'])} сообщений",
        parse_mode="Markdown"
    )

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = load_memory(update.effective_user.id).get("stats", {})
    await update.message.reply_text(
        f"📊 *Статистика:*\n💬 {s.get('messages',0)} | 💻 {s.get('codes_generated',0)} | "
        f"📸 {s.get('images_analyzed',0)} | 🎤 {s.get('voices_processed',0)} | "
        f"👍 {s.get('positive_feedback',0)} / 👎 {s.get('negative_feedback',0)}",
        parse_mode="Markdown"
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    memory = load_memory(user_id)
    memory["history"] = []
    save_memory(memory, user_id)
    await update.message.reply_text("🗑 История очищена!")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрируем команды — появятся в меню Telegram
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start",   "🏠 Главное меню"),
            BotCommand("ping",    "🤖 Проверить все AI"),
            BotCommand("memory",  "🧠 Что я помню"),
            BotCommand("stats",   "📊 Статистика"),
            BotCommand("clear",   "🗑 Очистить историю"),
            BotCommand("help",    "❓ Помощь"),
        ])

    app.post_init = set_commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("🤖 Бот запущен! Groq + OpenRouter + Cohere + Gemini")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
