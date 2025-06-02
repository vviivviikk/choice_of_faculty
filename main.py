import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
import psycopg2
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=os.getenv("BOT_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())


def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST")
    )


class FacultyStates(StatesGroup):
    waiting_for_favorite_subjects = State()
    waiting_for_disliked_subjects = State()
    waiting_for_passed_exams = State()


@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    await message.answer("Здравствуйте. Я помогу подобрать Вам подходящий факультет и профессию.\n\n"
                         "Расскажите, какие предметы в школе тебе НРАВЯТСЯ (перечислите через запятую).")
    await state.set_state(FacultyStates.waiting_for_favorite_subjects)


@dp.message(FacultyStates.waiting_for_favorite_subjects)
async def process_favorite_subjects(message: types.Message, state: FSMContext):
    fav = [s.strip().lower() for s in message.text.split(",")]
    await state.update_data(favorite_subjects=fav)
    await message.answer("Спасибо! А теперь укажите предметы, которые Вам НЕ нравятся (через запятую).")
    await state.set_state(FacultyStates.waiting_for_disliked_subjects)


@dp.message(FacultyStates.waiting_for_disliked_subjects)
async def process_disliked_subjects(message: types.Message, state: FSMContext):
    disliked = [s.strip().lower() for s in message.text.split(",")]
    await state.update_data(disliked_subjects=disliked)
    await message.answer("Хорошо! Теперь напишите, какие экзамены вы уже сдали или планируете сдавать (через запятую).")
    await state.set_state(FacultyStates.waiting_for_passed_exams)


@dp.message(FacultyStates.waiting_for_passed_exams)
async def process_passed_exams(message: types.Message, state: FSMContext):
    exams = [s.strip().lower() for s in message.text.split(",")]
    data = await state.get_data()

    favorite_subjects = set(data['favorite_subjects'])
    disliked_subjects = set(data['disliked_subjects'])
    passed_exams = set(exams)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id, name, required_subjects, optional_subjects FROM faculties')
            faculties = cur.fetchall()
    finally:
        conn.close()

    recommended = None
    best_score = -1

    for fac_id, fac_name, required, optional in faculties:
        required = set([s.strip().lower() for s in required])
        optional = set([s.strip().lower() for s in optional]) if optional else set()

        req_matched = len(required & (favorite_subjects | passed_exams))
        opt_matched = len(optional & (favorite_subjects | passed_exams))
        disliked_matched = len(required & disliked_subjects)

        if not required.issubset(passed_exams):
            continue

        score = req_matched * 2 + opt_matched - disliked_matched * 2

        if score > best_score:
            best_score = score
            recommended = (fac_id, fac_name, required, optional)

    if recommended:
        fac_id, fac_name, required, optional = recommended
        profession = pick_profession(fac_name)
        await message.answer(
            f"✨ Я рекомендую Вам факультет: <b>{fac_name}</b>!\n"
            f"А возможная профессия для Вас: <b>{profession}</b>.\n\n"
            f"Обязательные предметы: {', '.join(required)}\n"
            f"Дополнительные: {', '.join(optional) if optional else '-'}"
        )
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO recommendations (user_id, recommended_faculty_id, favorite_subjects, disliked_subjects, passed_exams) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (message.from_user.id, fac_id, list(favorite_subjects), list(disliked_subjects), list(passed_exams))
                )
                conn.commit()
        finally:
            conn.close()
    else:
        await message.answer(
            "🧐 К сожалению, я не смог подобрать подходящий факультет на основании твоих данных. "
            "Возможно, стоит попробовать сдать ещё нужные экзамены или выбрать другие факультеты."
        )
    await state.clear()


def pick_profession(faculty_name: str) -> str:
    map_prof = {
        'информатики и вычислительной техники': "программист, инженер по ИТ, системный архитектор",
        'филологии': "учитель русского языка, корректор, редактор, переводчик",
        'биологии': "биолог, лаборант, эколог, микробиолог",
        'экономический': "экономист, бухгалтер, аналитик, финансист",
        'иностранных языков': "переводчик, преподаватель, лингвист, гид"
    }
    for f, prof in map_prof.items():
        if f in faculty_name.lower():
            return prof
    return "универсальный профессионал"


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())