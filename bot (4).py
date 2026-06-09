import os
import json
import logging
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
OWNER_ID         = int(os.environ.get("OWNER_ID", "0"))   # Telegram ID владельца
ADMINS_FILE      = "admins.json"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ─── Admins storage ────────────────────────────────────────────────────────────
def load_admins() -> set:
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_admins(admins: set):
    with open(ADMINS_FILE, "w") as f:
        json.dump(list(admins), f)

admins: set = load_admins()

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in admins

# ─── Conversation history ───────────────────────────────────────────────────────
history: dict[int, list] = {}
MAX_HISTORY = 30

SYSTEM_PROMPT = """Ты — ИИ-ведущий масштабной ролевой игры по странам мира (геополитическое РП).

ТВОИ ЗАДАЧИ:
1. **Проверка новостей на реалистичность** — когда игрок присылает новость от своей страны, ты оцениваешь:
   - Логична ли она для данной страны и текущего года?
   - Соответствует ли она реальным возможностям страны (экономика, армия, география)?
   - Нет ли противоречий с другими событиями в РП?
   Даёшь 2–4 коротких совета по улучшению, но НЕ пишешь новость за игрока.

2. **Вердикты** — официальный ответ администрации на новость игрока:
   - Принята ✅ / Частично принята ⚠️ / Отклонена ❌
   - Краткое объяснение решения
   - Возможные последствия для РП
   Вердикты выносишь только по запросу администратора (/verdict).

3. **Ответы на РП-вопросы** — помогаешь игрокам разобраться в механиках, ситуациях, отношениях между странами.

4. **Год** — если тебе нужен текущий год РП, уточняй у игрока. Запоминай год в разговоре.

ПРАВИЛА ПОВЕДЕНИЯ:
- Ты строгий, но справедливый ведущий. Стиль — деловой, чёткий.
- Отвечай на русском языке.
- Никогда не пиши новости за игроков — только советы и оценки.
- Если сообщение не связано с РП — вежливо напоминай, что ты ведущий РП по странам.
- Используй эмодзи умеренно для наглядности (🌍 ⚔️ 📰 ✅ ❌ ⚠️).
"""

# ─── Gemini call ───────────────────────────────────────────────────────────────
def ask_gemini(user_id: int, user_message: str, extra_context: str = "") -> str:
    if user_id not in history:
        history[user_id] = []

    full_message = extra_context + user_message if extra_context else user_message
    history[user_id].append({"role": "user", "parts": [full_message]})

    if len(history[user_id]) > MAX_HISTORY:
        history[user_id] = history[user_id][-MAX_HISTORY:]

    try:
        chat = model.start_chat(history=history[user_id][:-1])
        response = chat.send_message(
            history[user_id][-1]["parts"][0],
            generation_config={"max_output_tokens": 1024},
            system_instruction=SYSTEM_PROMPT
        )
        reply = response.text
        history[user_id].append({"role": "model", "parts": [reply]})
        return reply
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "⚠️ Ошибка при обращении к ИИ. Попробуй ещё раз."

# ─── Commands ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    history[uid] = []
    role = "👑 Владелец" if is_owner(uid) else ("🛡️ Администратор" if is_admin(uid) else "🌍 Игрок")
    await update.message.reply_text(
        f"*Добро пожаловать в РП по странам!* {role}\n\n"
        "Я — ведущий этой ролевой игры. Вот что я умею:\n\n"
        "📰 *Проверка новостей* — пришли новость, я дам советы\n"
        "⚖️ */verdict* — вынести вердикт по новости _(только для админов)_\n"
        "❓ Любой РП-вопрос — просто напиши\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/clear — очистить историю\n"
        "/admins — список администраторов\n"
        "/addadmin @username или ID _(только владелец)_\n"
        "/removeadmin @username или ID _(только владелец)_\n"
        "/verdict _(только для админов)_ — вынести вердикт на последнюю новость",
        parse_mode="Markdown"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history[update.effective_user.id] = []
    await update.message.reply_text("🗑️ История очищена.")

async def admins_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admins:
        await update.message.reply_text(f"👑 Владелец: `{OWNER_ID}`\n🛡️ Администраторов пока нет.", parse_mode="Markdown")
        return
    lines = [f"👑 Владелец: `{OWNER_ID}`", "🛡️ *Администраторы:*"] + [f"• `{a}`" for a in admins]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Только владелец может назначать администраторов.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /addadmin <ID>")
        return
    try:
        new_id = int(re.sub(r"[^0-9]", "", context.args[0]))
        admins.add(new_id)
        save_admins(admins)
        await update.message.reply_text(f"✅ Пользователь `{new_id}` назначен администратором.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Укажи числовой Telegram ID.")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Только владелец может снимать администраторов.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /removeadmin <ID>")
        return
    try:
        rem_id = int(re.sub(r"[^0-9]", "", context.args[0]))
        if rem_id in admins:
            admins.discard(rem_id)
            save_admins(admins)
            await update.message.reply_text(f"✅ Пользователь `{rem_id}` снят с должности администратора.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ Пользователь `{rem_id}` не является администратором.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Укажи числовой Telegram ID.")

async def verdict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Вердикты могут выносить только администраторы.")
        return
    await update.message.chat.send_action("typing")
    extra = "[РЕЖИМ АДМИНИСТРАТОРА] Вынеси официальный вердикт по последней новости в нашем диалоге. Формат: статус (Принята/Частично/Отклонена), обоснование, последствия для РП.\n"
    reply = ask_gemini(uid, "/verdict", extra_context=extra)
    await update.message.reply_text(reply)

# ─── Message handler ───────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    await update.message.chat.send_action("typing")

    # Добавляем контекст роли пользователя
    role_ctx = ""
    if is_owner(uid):
        role_ctx = "[Пишет ВЛАДЕЛЕЦ сервера — имеет все права]\n"
    elif is_admin(uid):
        role_ctx = "[Пишет АДМИНИСТРАТОР — имеет права выносить вердикты и управлять игрой]\n"
    else:
        role_ctx = "[Пишет обычный ИГРОК]\n"

    reply = ask_gemini(uid, text, extra_context=role_ctx)
    await update.message.reply_text(reply)

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_TOKEN_HERE":
        raise ValueError("Укажи TELEGRAM_TOKEN!")
    if GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        raise ValueError("Укажи GEMINI_API_KEY!")
    if OWNER_ID == 0:
        raise ValueError("Укажи OWNER_ID — твой Telegram ID!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("admins", admins_list))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("removeadmin", remove_admin))
    app.add_handler(CommandHandler("verdict", verdict))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("РП-бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
