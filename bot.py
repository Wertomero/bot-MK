import asyncio
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import BotCommand

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_URL = os.getenv("DB_URL")

# ID создателя (замени на свой)
CREATOR_ID = 7989127445


def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        user_id BIGINT PRIMARY KEY, username TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS job_applications (
        id SERIAL PRIMARY KEY, user_id BIGINT, username TEXT, sphere TEXT, experience TEXT, contacts TEXT, timezone TEXT, created_at TIMESTAMP DEFAULT NOW(), status TEXT DEFAULT 'new')""")
    c.execute("""CREATE TABLE IF NOT EXISTS ideas (
        id SERIAL PRIMARY KEY, user_id BIGINT, username TEXT, description TEXT, created_at TIMESTAMP DEFAULT NOW(), status TEXT DEFAULT 'new')""")
    c.execute("""CREATE TABLE IF NOT EXISTS direct_chat_requests (
        id SERIAL PRIMARY KEY, user_id BIGINT, username TEXT, who TEXT, reason TEXT, created_at TIMESTAMP DEFAULT NOW(), status TEXT DEFAULT 'pending')""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_chats (
        id SERIAL PRIMARY KEY, user_id BIGINT, admin_id BIGINT, created_at TIMESTAMP DEFAULT NOW(), status TEXT DEFAULT 'active')""")
    c.execute("INSERT INTO admins (user_id, username) VALUES (%s, 'Creator') ON CONFLICT (user_id) DO NOTHING", (CREATOR_ID,))
    conn.close()


def is_admin(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=%s", (uid,))
    r = c.fetchone()
    conn.close()
    return r is not None


def add_admin(uid, uname):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO admins (user_id, username) VALUES (%s,%s) ON CONFLICT (user_id) DO NOTHING", (uid, uname))
    conn.close()


def remove_admin(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=%s", (uid,))
    conn.close()


def get_all_admins():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM admins")
    return c.fetchall()


def add_job_application(uid, uname, sphere, experience, contacts, timezone):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO job_applications (user_id, username, sphere, experience, contacts, timezone) VALUES (%s,%s,%s,%s,%s,%s)", (uid, uname, sphere, experience, contacts, timezone))
    conn.close()


def add_idea(uid, uname, description):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO ideas (user_id, username, description) VALUES (%s,%s,%s)", (uid, uname, description))
    conn.close()


def add_chat_request(uid, uname, who, reason):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO direct_chat_requests (user_id, username, who, reason) VALUES (%s,%s,%s,%s)", (uid, uname, who, reason))
    conn.close()


def get_pending_requests():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM direct_chat_requests WHERE status='pending' ORDER BY created_at DESC")
    return c.fetchall()


def update_chat_request(rid, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE direct_chat_requests SET status=%s WHERE id=%s", (status, rid))
    conn.close()


def create_chat(uid, admin_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO active_chats (user_id, admin_id) VALUES (%s,%s)", (uid, admin_id))
    conn.close()


def close_chat(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE active_chats SET status='closed' WHERE user_id=%s AND status='active'", (uid,))
    conn.close()


def get_active_chat(uid):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM active_chats WHERE user_id=%s AND status='active'", (uid,))
    return c.fetchone()


def get_admin_active_chats(admin_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM active_chats WHERE admin_id=%s AND status='active'", (admin_id,))
    return c.fetchall()


def get_job_applications():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM job_applications ORDER BY created_at DESC")
    return c.fetchall()


def get_ideas():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM ideas ORDER BY created_at DESC")
    return c.fetchall()


# ========== СОСТОЯНИЯ ==========
class JobForm(StatesGroup):
    waiting_for_sphere = State()
    waiting_for_experience = State()
    waiting_for_contacts = State()
    waiting_for_timezone = State()


class IdeaForm(StatesGroup):
    waiting_for_description = State()


class DirectForm(StatesGroup):
    waiting_for_who = State()
    waiting_for_reason = State()


class ChatState(StatesGroup):
    in_chat = State()


class AdminStates(StatesGroup):
    waiting_for_admin_add = State()
    waiting_for_admin_remove = State()


router = Router()


# ========== СТАРТ ==========
@router.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Подать заявку на работу в МК", callback_data="job_apply")],
        [InlineKeyboardButton(text="💡 Подать идею для МК", callback_data="idea_submit")],
        [InlineKeyboardButton(text="📞 Прямая связь с руководством", callback_data="direct_chat")],
    ])
    await msg.answer("Добро пожаловать в Министерство Культуры!\nВыберите действие:", reply_markup=kb)


# ========== АДМИН-ПАНЕЛЬ ==========
@router.message(Command("adminMK"))
async def admin_panel(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer("🚫 Команда не найдена.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Заявки на работу", callback_data="admin_jobs")],
        [InlineKeyboardButton(text="💡 Идеи", callback_data="admin_ideas")],
        [InlineKeyboardButton(text="📞 Запросы на связь", callback_data="admin_requests")],
        [InlineKeyboardButton(text="💬 Активные чаты", callback_data="admin_chats")],
        [InlineKeyboardButton(text="👥 Управление админами", callback_data="admin_manage")],
    ])
    await msg.answer("🔐 Админ-панель МК", reply_markup=kb)


# ========== ЗАЯВКА НА РАБОТУ ==========
@router.callback_query(F.data == "job_apply")
async def job_apply_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📋 <b>Заявка на работу в МК</b>\n\nВ какой сфере хотите работать?", parse_mode="HTML")
    await state.set_state(JobForm.waiting_for_sphere)


@router.message(JobForm.waiting_for_sphere)
async def job_sphere(msg: Message, state: FSMContext):
    await state.update_data(sphere=msg.text.strip())
    await msg.answer("Где у вас есть опыт работы?")
    await state.set_state(JobForm.waiting_for_experience)


@router.message(JobForm.waiting_for_experience)
async def job_experience(msg: Message, state: FSMContext):
    await state.update_data(experience=msg.text.strip())
    await msg.answer("Введите контактные данные (телефон/почта/телеграм):")
    await state.set_state(JobForm.waiting_for_contacts)


@router.message(JobForm.waiting_for_contacts)
async def job_contacts(msg: Message, state: FSMContext):
    await state.update_data(contacts=msg.text.strip())
    await msg.answer("Разница во времени с Москвой? (например: +2, -1, +4):")
    await state.set_state(JobForm.waiting_for_timezone)


@router.message(JobForm.waiting_for_timezone)
async def job_timezone(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    add_job_application(msg.from_user.id, msg.from_user.username or "—", data['sphere'], data['experience'], data['contacts'], msg.text.strip())
    await state.clear()
    await msg.answer("✅ Заявка отправлена! Ожидайте рассмотрения.")
    
    # Уведомление админам
    admins = get_all_admins()
    text = f"📋 <b>Новая заявка на работу!</b>\n👤 @{msg.from_user.username or '—'}\n🏢 Сфера: {data['sphere']}\n📝 Опыт: {data['experience']}\n📞 Контакты: {data['contacts']}\n🕐 Часовой пояс: {msg.text.strip()}"
    for a in admins:
        try:
            await bot.send_message(a['user_id'], text, parse_mode="HTML")
        except:
            pass


# ========== ПОДАТЬ ИДЕЮ ==========
@router.callback_query(F.data == "idea_submit")
async def idea_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("💡 <b>Подача идеи</b>\n\nОпишите вашу идею для Министерства Культуры:", parse_mode="HTML")
    await state.set_state(IdeaForm.waiting_for_description)


@router.message(IdeaForm.waiting_for_description)
async def idea_done(msg: Message, state: FSMContext, bot: Bot):
    add_idea(msg.from_user.id, msg.from_user.username or "—", msg.text.strip())
    await state.clear()
    await msg.answer("✅ Идея отправлена! Спасибо за вклад в развитие.")
    
    admins = get_all_admins()
    text = f"💡 <b>Новая идея!</b>\n👤 @{msg.from_user.username or '—'}\n📝 {msg.text.strip()}"
    for a in admins:
        try:
            await bot.send_message(a['user_id'], text, parse_mode="HTML")
        except:
            pass


# ========== ПРЯМАЯ СВЯЗЬ ==========
@router.callback_query(F.data == "direct_chat")
async def direct_chat_start(cb: CallbackQuery, state: FSMContext):
    # Проверяем есть ли уже активный чат
    chat = get_active_chat(cb.from_user.id)
    if chat:
        await cb.message.edit_text("📞 У вас уже есть активный чат. Отправьте сообщение сюда.")
        await state.set_state(ChatState.in_chat)
        return
    
    await cb.message.edit_text("📞 <b>Запрос прямой связи</b>\n\nПредставьтесь, кто вы?", parse_mode="HTML")
    await state.set_state(DirectForm.waiting_for_who)


@router.message(DirectForm.waiting_for_who)
async def direct_who(msg: Message, state: FSMContext):
    await state.update_data(who=msg.text.strip())
    await msg.answer("Зачем вам нужна прямая связь? Опишите вопрос.")
    await state.set_state(DirectForm.waiting_for_reason)


@router.message(DirectForm.waiting_for_reason)
async def direct_reason(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    add_chat_request(msg.from_user.id, msg.from_user.username or "—", data['who'], msg.text.strip())
    await state.clear()
    await msg.answer("✅ Запрос отправлен! Ожидайте одобрения руководством.")
    
    admins = get_all_admins()
    text = f"📞 <b>Запрос прямой связи!</b>\n👤 @{msg.from_user.username or '—'}\n🙋 {data['who']}\n📝 Причина: {msg.text.strip()}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{msg.from_user.id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_{msg.from_user.id}")]])
    for a in admins:
        try:
            await bot.send_message(a['user_id'], text, parse_mode="HTML", reply_markup=kb)
        except:
            pass


# ========== АДМИН: ОДОБРЕНИЕ/ОТКЛОНЕНИЕ СВЯЗИ ==========
@router.callback_query(F.data.startswith("approve_"))
async def approve_chat(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    uid = int(cb.data.split("_")[1])
    create_chat(uid, cb.from_user.id)
    await cb.message.edit_text(cb.message.text + "\n\n✅ Одобрено!")
    try:
        await bot.send_message(uid, "✅ Ваш запрос на прямую связь одобрен! Отправьте сообщение сюда.")
    except:
        pass


@router.callback_query(F.data.startswith("decline_"))
async def decline_chat(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    uid = int(cb.data.split("_")[1])
    await cb.message.edit_text(cb.message.text + "\n\n❌ Отклонено!")
    try:
        await bot.send_message(uid, "❌ Ваш запрос на прямую связь отклонён.")
    except:
        pass


# ========== ПЕРЕСЫЛКА СООБЩЕНИЙ В ЧАТЕ ==========
@router.message(ChatState.in_chat)
async def chat_message(msg: Message, bot: Bot):
    chat = get_active_chat(msg.from_user.id)
    if not chat:
        await msg.answer("❌ Чат не активен.")
        return
    
    # Если пишет пользователь — пересылаем админу
    if msg.from_user.id == chat['user_id']:
        text = f"💬 <b>От:</b> @{msg.from_user.username or '—'}\n{msg.text}"
        try:
            await bot.send_message(chat['admin_id'], text, parse_mode="HTML")
        except:
            await msg.answer("❌ Сообщение не доставлено.")
    # Если пишет админ — пересылаем пользователю
    elif msg.from_user.id == chat['admin_id']:
        text = f"💬 <b>От руководства:</b>\n{msg.text}"
        try:
            await bot.send_message(chat['user_id'], text, parse_mode="HTML")
        except:
            await msg.answer("❌ Сообщение не доставлено.")


# ========== АДМИН: ПРОСМОТР ЗАЯВОК ==========
@router.callback_query(F.data == "admin_jobs")
async def admin_jobs(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    jobs = get_job_applications()
    if not jobs:
        await cb.message.edit_text("📋 Нет заявок.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))
        return
    text = "📋 <b>Заявки на работу:</b>\n\n"
    for j in jobs[:10]:
        text += f"🆔 {j['id']} | @{j['username']} | {j['sphere']}\n📝 {j['experience'][:50]}...\n📞 {j['contacts']} | 🕐 {j['timezone']}\n\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))


@router.callback_query(F.data == "admin_ideas")
async def admin_ideas(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    ideas = get_ideas()
    if not ideas:
        await cb.message.edit_text("💡 Нет идей.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))
        return
    text = "💡 <b>Идеи:</b>\n\n"
    for i in ideas[:10]:
        text += f"🆔 {i['id']} | @{i['username']}\n📝 {i['description'][:100]}...\n\n"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))


@router.callback_query(F.data == "admin_requests")
async def admin_requests(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    reqs = get_pending_requests()
    if not reqs:
        await cb.message.edit_text("📞 Нет запросов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))
        return
    text = "📞 <b>Запросы на связь:</b>\n\n"
    kb = []
    for r in reqs:
        text += f"🆔 {r['id']} | @{r['username']} | {r['who']}\n📝 {r['reason'][:50]}...\n\n"
        kb.append([InlineKeyboardButton(text=f"✅ {r['username']}", callback_data=f"approve_{r['user_id']}"),
                   InlineKeyboardButton(text=f"❌ {r['username']}", callback_data=f"decline_{r['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "admin_chats")
async def admin_chats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    chats = get_admin_active_chats(cb.from_user.id)
    if not chats:
        await cb.message.edit_text("💬 Нет активных чатов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))
        return
    text = "💬 <b>Активные чаты:</b>\n\n"
    kb = []
    for ch in chats:
        text += f"🆔 {ch['id']} | user_id: {ch['user_id']}\n"
        kb.append([InlineKeyboardButton(text=f"📩 Чат с {ch['user_id']}", callback_data=f"openchat_{ch['user_id']}")])
        kb.append([InlineKeyboardButton(text=f"🔒 Закрыть чат {ch['user_id']}", callback_data=f"closechat_{ch['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("openchat_"))
async def open_chat_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    uid = int(cb.data.split("_")[1])
    await state.set_state(ChatState.in_chat)
    await cb.message.edit_text(f"💬 Чат открыт. Отправьте сообщение пользователю {uid}.\n/close — закрыть чат")


@router.callback_query(F.data.startswith("closechat_"))
async def close_chat_admin(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    uid = int(cb.data.split("_")[1])
    close_chat(uid)
    await cb.answer("🔒 Чат закрыт!")
    try:
        await bot.send_message(uid, "🔒 Чат закрыт руководством. Если остались вопросы — подайте новый запрос.")
    except:
        pass
    await admin_chats(cb)


# ========== АДМИН: УПРАВЛЕНИЕ АДМИНАМИ ==========
@router.callback_query(F.data == "admin_manage")
async def admin_manage(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    admins = get_all_admins()
    text = "👥 <b>Администраторы:</b>\n\n"
    for a in admins:
        text += f"• {a['user_id']} | @{a['username']}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")],
    ])
    await cb.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "admin_add")
async def admin_add_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    await cb.message.edit_text("Введите user_id нового админа:")
    await state.set_state(AdminStates.waiting_for_admin_add)


@router.message(AdminStates.waiting_for_admin_add)
async def admin_add_done(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text.strip())
    except:
        await msg.answer("❌ Число!")
        return
    add_admin(uid, "admin")
    await state.clear()
    await msg.answer(f"✅ Админ {uid} добавлен!")
    await admin_panel(msg)


@router.callback_query(F.data == "admin_remove")
async def admin_remove_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    await cb.message.edit_text("Введите user_id админа для удаления:")
    await state.set_state(AdminStates.waiting_for_admin_remove)


@router.message(AdminStates.waiting_for_admin_remove)
async def admin_remove_done(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text.strip())
    except:
        await msg.answer("❌ Число!")
        return
    if uid == CREATOR_ID:
        await msg.answer("❌ Нельзя удалить создателя!")
        return
    remove_admin(uid)
    await state.clear()
    await msg.answer(f"✅ Админ {uid} удалён!")
    await admin_panel(msg)


@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    await admin_panel(cb)


# ========== КОМАНДА ЗАКРЫТИЯ ЧАТА ==========
@router.message(Command("close"))
async def close_chat_user(msg: Message, state: FSMContext, bot: Bot):
    chat = get_active_chat(msg.from_user.id)
    if chat:
        close_chat(msg.from_user.id)
        await state.clear()
        await msg.answer("🔒 Чат закрыт.")
        try:
            await bot.send_message(chat['admin_id'], f"🔒 Пользователь {msg.from_user.id} закрыл чат.")
        except:
            pass
    else:
        await msg.answer("У вас нет активного чата.")


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
    ])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
