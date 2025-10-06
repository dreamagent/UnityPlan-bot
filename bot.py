import asyncio, os, logging
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiosqlite

# === OpenAI ===
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

assert BOT_TOKEN, "❌ BOT_TOKEN не знайдено в .env"
assert OPENAI_API_KEY, "❌ OPENAI_API_KEY не знайдено в .env"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = OpenAI(api_key=OPENAI_API_KEY)  # ініціалізація SDK

DB_PATH = "data.db"

# ---------- База даних (цілі) ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()

async def add_goal(user_id: int, text: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO goals(user_id, text, is_done, created_at) VALUES (?, ?, 0, ?)",
            (user_id, text, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid

async def list_goals(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, text, is_done FROM goals WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        )
        return await cur.fetchall()

async def mark_done(user_id: int, goal_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE goals SET is_done=1 WHERE id=? AND user_id=?",
            (goal_id, user_id),
        )
        await db.commit()
        return cur.rowcount

async def delete_goal(user_id: int, goal_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM goals WHERE id=? AND user_id=?",
            (goal_id, user_id),
        )
        await db.commit()
        return cur.rowcount

# ---------- Кнопки ----------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🧠 Запитати AI"), KeyboardButton(text="🎯 Мої цілі")],
        [KeyboardButton(text="🚀 Новий челендж"), KeyboardButton(text="📅 План на сьогодні")],
    ],
    resize_keyboard=True
)

# ---------- Допоміжне: виклик OpenAI ----------
async def ask_openai(prompt: str) -> str:
    """
    Питаємо OpenAI і повертаємо коротку відповідь.
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",  # швидко/дешево; можна замінити на потужнішу
            messages=[
                {"role": "system", "content": "You are GPT-5 Thinking, a helpful planning assistant for productivity, goals and daily focus. Answer concisely in Ukrainian unless asked otherwise."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.exception("OpenAI error")
        return "⚠️ Вибач, зараз не вдається отримати відповідь від AI."

# ---------- Команди ----------
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Привіт, я UnityPlan Bot з AI!\n"
        "Команди:\n"
        "• /ask твоє_питання — запит до AI\n"
        "• /addgoal Текст цілі — додати\n"
        "• /goals — список цілей\n"
        "• /done ID — позначити виконаною\n"
        "• /del ID — видалити\n",
        reply_markup=main_menu
    )

@dp.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject):
    question = (command.args or "").strip()
    if not question:
        await message.answer("Напиши так: `/ask Допоможи скласти план на день`", parse_mode="Markdown")
        return
    await message.answer("🧠 Думаю над відповіддю…")
    answer = await ask_openai(question)
    await message.answer(answer)

@dp.message(Command("addgoal"))
async def cmd_addgoal(message: Message, command: CommandObject):
    text = (command.args or "").strip()
    if not text:
        await message.answer("Введи так: `/addgoal Купити BMW S1000RR`", parse_mode="Markdown")
        return
    goal_id = await add_goal(message.from_user.id, text)
    await message.answer(f"✅ Ціль додано (ID: {goal_id})")

@dp.message(Command("goals"))
async def cmd_goals(message: Message):
    rows = await list_goals(message.from_user.id)
    if not rows:
        await message.answer("Поки що немає цілей. Додай через `/addgoal ...`", parse_mode="Markdown")
        return
    lines = []
    for _id, text, is_done in rows:
        status = "✅" if is_done else "⏳"
        lines.append(f"{status} *{_id}*. {text}")
    await message.answer("\n".join(lines), parse_mode="Markdown")

@dp.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject):
    if not command.args or not command.args.isdigit():
        await message.answer("Введи так: `/done 12` (де 12 — ID цілі)", parse_mode="Markdown")
        return
    changed = await mark_done(message.from_user.id, int(command.args))
    await message.answer("✅ Готово!" if changed else "❗️Не знайшов таку ціль.")

@dp.message(Command("del"))
async def cmd_del(message: Message, command: CommandObject):
    if not command.args or not command.args.isdigit():
        await message.answer("Введи так: `/del 12` (де 12 — ID цілі)", parse_mode="Markdown")
        return
    deleted = await delete_goal(message.from_user.id, int(command.args))
    await message.answer("🗑 Видалено." if deleted else "❗️Не знайшов таку ціль.")

# ---------- Обробка кнопок з меню ----------
@dp.message()
async def handle_buttons(message: Message):
    if message.text == "🧠 Запитати AI":
        await message.answer("Напиши команду у форматі: `/ask Твоє запитання`", parse_mode="Markdown")
    elif message.text == "🎯 Мої цілі":
        await cmd_goals(message)
    elif message.text == "🚀 Новий челендж":
        await message.answer("(Тут пізніше зробимо майстер створення челенджу)")
    elif message.text == "📅 План на сьогодні":
        await message.answer("(Тут пізніше підключимо план на день)")
    else:
        await message.answer("Вибери дію з меню 👇", reply_markup=main_menu)

# ---------- Головний цикл ----------
async def main():
    await init_db()
    logging.info("🚀 UnityPlan Bot + SQLite + OpenAI запущено!")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())
from openai import OpenAI

# ініціалізація клієнта
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@dp.message(Command("ask"))
async def ask_ai(message: Message):
    query = message.text.replace("/ask", "").strip()
    if not query:
        await message.answer("❓ Напиши запит у форматі: `/ask твоє_питання`")
        return

    await message.answer("🤖 Думаю над відповіддю...")

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ти — корисний асистент UnityPlan, який допомагає людям з цілями, планами і мотивацією."},
                {"role": "user", "content": query},
            ],
        )
        answer = response.choices[0].message.content
        await message.answer(f"🧠 Відповідь від AI:\n{answer}")

    except Exception as e:
        await message.answer("⚠️ Виникла помилка при зверненні до AI.")
        print(e)
