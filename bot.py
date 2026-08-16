from aiohttp import web
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

CREATOR_ID = 5091635656
ADMIN_PASSWORD = "mkpanel"


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
    c.execute("""CREATE TABLE IF NOT EXISTS flash_requests (
        id SERIAL PRIMARY KEY, user_id BIGINT, username TEXT, nickname TEXT, service_type TEXT, build_type TEXT, schematic TEXT, location TEXT, deadline TEXT, created_at TIMESTAMP DEFAULT NOW(), status TEXT DEFAULT 'new')""")
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


def add_flash_request(uid, uname, nickname, service_type, build_type, schematic, location, deadline):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO flash_requests (user_id, username, nickname, service_type, build_type, schematic, location, deadline) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
              (uid, uname, nickname, service_type, build_type, schematic, location, deadline))
    conn.close()


def get_flash_requests():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM flash_requests ORDER BY created_at DESC")
    return c.fetchall()


# ========== СОСТОЯНИЯ ==========
class JobForm(StatesGroup):
    waiting_for_sphere = State()
    waiting_for_experience = State()
    waiting_for_contacts = State()
    waiting_for_timezone = State()
    waiting_for_nickname = State()
    waiting_for_service_type = State()
    waiting_for_build_type = State()
    waiting_for_schematic = State()
    waiting_for_location = State()
    waiting_for_deadline = State()


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
    waiting_for_admin_password = State()


router = Router()


# ========== СТАРТ ==========
@router.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Подать заявку на работу в МК", callback_data="job_apply")],
        [InlineKeyboardButton(text="⚡ Заявка — Молниенос", callback_data="flash_apply")],
        [InlineKeyboardButton(text="💡 Подать идею для МК", callback_data="idea_submit")],
        [InlineKeyboardButton(text="📞 Прямая связь с руководством", callback_data="direct_chat")],
    ])
    await msg.answer("Добро пожаловать в Министерство Культуры!\nВыберите действие:", reply_markup=kb)


# ========== АДМИН-ПАНЕЛЬ ==========
@router.message(Command("adminMK"))
async def admin_panel_cmd(msg: Message, state: FSMContext):
    if is_admin(msg.from_user.id):
        await show_admin_panel(msg)
        return
    await msg.answer("🔐 Введите пароль:")
    await state.set_state(AdminStates.waiting_for_admin_password)


@router.message(AdminStates.waiting_for_admin_password)
async def check_admin_password(msg: Message, state: FSMContext):
    if msg.text.strip() == ADMIN_PASSWORD:
        await state.clear()
        add_admin(msg.from_user.id, msg.from_user.username or "admin")
        await show_admin_panel(msg)
    else:
        await msg.answer("❌ Неверный пароль!")
        await state.clear()


async def show_admin_panel(msg):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Заявки на работу", callback_data="admin_jobs")],
        [InlineKeyboardButton(text="⚡ Заявки Молниенос", callback_data="admin_flash")],
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
    
    admins = get_all_admins()
    text = f"📋 <b>Новая заявка на работу!</b>\n👤 @{msg.from_user.username or '—'}\n🏢 Сфера: {data['sphere']}\n📝 Опыт: {data['experience']}\n📞 Контакты: {data['contacts']}\n🕐 Часовой пояс: {msg.text.strip()}"
    for a in admins:
        try:
            await bot.send_message(a['user_id'], text, parse_mode="HTML")
        except:
            pass


# ========== ЗАЯВКА — МОЛНИЕНОС ==========
@router.callback_query(F.data == "flash_apply")
async def flash_apply_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("⚡ <b>Заявка — Молниенос</b>\n\n1. Введите ваш ник в игре:", parse_mode="HTML")
    await state.set_state(JobForm.waiting_for_nickname)


@router.message(JobForm.waiting_for_nickname)
async def flash_nickname(msg: Message, state: FSMContext):
    await state.update_data(nickname=msg.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Только сбор ресурсов", callback_data="service_collect")],
        [InlineKeyboardButton(text="🏗 Только постройка", callback_data="service_build")],
        [InlineKeyboardButton(text="🔨 Всё вместе", callback_data="service_all")],
    ])
    await msg.answer("2. Тип услуги:", reply_markup=kb)


@router.callback_query(F.data.startswith("service_"))
async def flash_service_type(cb: CallbackQuery, state: FSMContext):
    service_type = cb.data.replace("service_", "")
    await state.update_data(service_type=service_type)
    await cb.message.edit_text("3. Тип постройки/ивента:\n\n(здание, ивент, ферма и т.д.)")
    await state.set_state(JobForm.waiting_for_build_type)


@router.message(JobForm.waiting_for_build_type)
async def flash_build_type(msg: Message, state: FSMContext):
    await state.update_data(build_type=msg.text.strip())
    await msg.answer("4. Схематика:\n\n(если есть — отправьте файлом или напишите описание)")
    await state.set_state(JobForm.waiting_for_schematic)


@router.message(JobForm.waiting_for_schematic)
async def flash_schematic(msg: Message, state: FSMContext):
    await state.update_data(schematic=msg.text.strip() if msg.text else "Файл прилагается")
    await msg.answer("5. Место и расположение постройки:\n\n(подробно опишите где строить: координаты, сторона схематики, препятствия)")
    await state.set_state(JobForm.waiting_for_location)


@router.message(JobForm.waiting_for_location)
async def flash_location(msg: Message, state: FSMContext):
    await state.update_data(location=msg.text.strip())
    await msg.answer("6. Желаемый срок выполнения:")
    await state.set_state(JobForm.waiting_for_deadline)


@router.message(JobForm.waiting_for_deadline)
async def flash_deadline(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    service_map = {"collect": "📦 Только сбор ресурсов", "build": "🏗 Только постройка", "all": "🔨 Всё вместе"}
    service = service_map.get(data.get('service_type', ''), "Не указано")
    
    add_flash_request(msg.from_user.id, msg.from_user.username or "—", data['nickname'], service, data['build_type'], data['schematic'], data['location'], msg.text.strip())
    
    await state.clear()
    await msg.answer("✅ <b>Заявка отправлена!</b>\n\nДалее с вами свяжется менеджер и напишет сумму.", parse_mode="HTML")
    
    admins = get_all_admins()
    text = (
        f"⚡ <b>Новая заявка — Молниенос!</b>\n\n"
        f"👤 @{msg.from_user.username or '—'}\n"
        f"🎮 Ник: {data['nickname']}\n"
        f"📋 Тип услуги: {service}\n"
        f"🏗 Постройка: {data['build_type']}\n"
        f"📐 Схематика: {data['schematic']}\n"
        f"📍 Место: {data['location']}\n"
        f"⏳ Срок: {msg.text.strip()}"
    )
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
    
    if msg.from_user.id == chat['user_id']:
        text = f"💬 <b>От:</b> @{msg.from_user.username or '—'}\n{msg.text}"
        try:
            await bot.send_message(chat['admin_id'], text, parse_mode="HTML")
        except:
            await msg.answer("❌ Сообщение не доставлено.")
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
    kb = []
    for j in jobs[:10]:
        text += f"🆔 {j['id']} | @{j['username']} | {j['sphere']}\n📝 {j['experience'][:50]}...\n📞 {j['contacts']} | 🕐 {j['timezone']}\n\n"
        kb.append([InlineKeyboardButton(text=f"📩 Уведомить @{j['username']}", callback_data=f"notify_job_{j['user_id']}_{j['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("notify_job_"))
async def notify_job_applicant(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    parts = cb.data.split("_")
    uid = int(parts[2])
    jid = parts[3]
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE job_applications SET status='notified' WHERE id=%s", (jid,))
    conn.close()

    try:
        await bot.send_message(uid, "✅ <b>Ваша заявка на работу в МК принята!</b>\nОжидайте дальнейших указаний от руководства.", parse_mode="HTML")
        await cb.answer("✅ Уведомление отправлено!")
    except:
        await cb.answer("❌ Не удалось отправить уведомление!")
    
    await admin_jobs(cb)


@router.callback_query(F.data == "admin_flash")
async def admin_flash(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    requests = get_flash_requests()
    if not requests:
        await cb.message.edit_text("⚡ Нет заявок.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]]))
        return
    
    text = "⚡ <b>Заявки — Молниенос:</b>\n\n"
    for r in requests[:10]:
        text += f"🆔 {r['id']} | @{r['username']} | 🎮 {r['nickname']}\n📋 {r['service_type']}\n🏗 {r['build_type']}\n⏳ {r['deadline']}\n\n"
    
    kb = [[InlineKeyboardButton(text=f"📋 Заявка #{r['id']}", callback_data=f"flash_detail_{r['id']}")] for r in requests[:10]]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("flash_detail_"))
async def flash_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа!")
        return
    rid = int(cb.data.split("_")[2])
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM flash_requests WHERE id=%s", (rid,))
    r = c.fetchone()
    conn.close()
    
    if not r:
        await cb.answer("Заявка не найдена")
        return
    
    text = (
        f"⚡ <b>Заявка #{rid}</b>\n\n"
        f"👤 @{r['username']}\n"
        f"🎮 Ник: {r['nickname']}\n"
        f"📋 Тип: {r['service_type']}\n"
        f"🏗 Постройка: {r['build_type']}\n"
        f"📐 Схематика: {r['schematic']}\n"
        f"📍 Место: {r['location']}\n"
        f"⏳ Срок: {r['deadline']}"
    )
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К заявкам", callback_data="admin_flash")]]))


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
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


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
        add_admin(uid, "admin")
        await state.clear()
        await msg.answer(f"✅ Админ {uid} добавлен!")
        await show_admin_panel(msg)
    except:
        await msg.answer("❌ Ошибка!")
        await state.clear()


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
        if uid == CREATOR_ID:
            await msg.answer("❌ Нельзя удалить создателя!")
            await state.clear()
            return
        remove_admin(uid)
        await state.clear()
        await msg.answer(f"✅ Админ {uid} удалён!")
        await show_admin_panel(msg)
    except:
        await msg.answer("❌ Ошибка!")
        await state.clear()


@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    await show_admin_panel(cb.message)


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


async def handle(request):
    return web.Response(text="Bot is running")


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
    ])
    
    # Веб-сервер для Render
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер на порту {port}")
    
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
