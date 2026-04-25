import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

import config
import database as db

logger = logging.getLogger(__name__)

# ── Bot va Dispatcher ─────────────────────────────────────────────────────────

bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Global userbot referensi (main.py orqali ulanadi)
userbot = None

# ── Majburiy obuna kanallari ──────────────────────────────────────────────────
REQUIRED_CHANNELS = [
    {"username": "ortiqboyovichch", "title": "Ortiqboyovich", "url": "https://t.me/ortiqboyovichch"},
    {"username": "jildgaqoshil", "title": "Jildga Qo'shil", "url": "https://t.me/jildgaqoshil"},
]

# ── FSM Holatlari ─────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Konkurs jildi (folder) botiga xush kelibsiz.\n"
        "Kanal qo'shish uchun @username yoki t.me linkini yuboring."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Kanallar", callback_data="list_channels"),
            InlineKeyboardButton(text="📂 Jild Linki", callback_data="get_link"),
        ]
    ])

    if message.from_user.id == config.ADMIN_ID:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="📊 Statistika", callback_data="stats"),
            InlineKeyboardButton(text="✉️ Reklama", callback_data="broadcast"),
        ])

    await message.answer(welcome_text, reply_markup=kb)

# ── Kanal qo'shish (Xatolik tuzatilgan variant) ───────────────────────────────

@router.message(F.text.contains("t.me/") | F.text.startswith("@"))
async def handle_link(message: Message):
    if message.from_user.id != config.ADMIN_ID:
        return

    text = message.text.strip()
    # Linkdan username ajratishni to'g'irlaymiz
    username = text.split('/')[-1].replace("@", "").split('?')[0]
    
    msg = await message.answer("🔍 Kanal tekshirilmoqda...")
    try:
        chat = await bot.get_chat(f"@{username}")
        db.add_channel(chat.id, chat.username, chat.title, text)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_{chat.id}")]
        ])
        await msg.edit_text(f"✅ <b>{chat.title}</b> bazaga qo'shildi!\nKanalda bot admin bo'lishi shart.", reply_markup=kb)
    except Exception as e:
        logger.error(f"Kanal xatosi: {e}")
        await msg.edit_text("❌ Kanal topilmadi. Botni kanalga admin qilib, so'ng username yuboring.")

# ── Jild Linkini olish (Skrinshotingdagi xato shu yerda edi) ───────────────────

@router.callback_query(F.data == "get_link")
async def send_folder_link(call: CallbackQuery):
    # Userbot ulanmagan bo'lsa xato bermasligi uchun tekshiruv
    if userbot is None:
        return await call.answer("❌ UserBot hali ulanmadi yoki xato berdi!", show_alert=True)
    
    await call.message.edit_text("⏳ Jild tayyorlanmoqda...")
    
    # create_folder_link'ni chaqiramiz
    result = await userbot.create_folder_link()
    
    # Ikkita qiymat (link, error) qaytishini tekshiramiz
    if isinstance(result, tuple):
        link, error = result
    else:
        link, error = result, None

    if link:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Jildga qo'shilish", url=link)]
        ])
        await call.message.answer(f"📂 <b>Konkurs jildi tayyor!</b>\n\nLink: <code>{link}</code>", reply_markup=kb)
        await call.message.delete()
    else:
        await call.message.answer(f"❌ Xatolik: {error if error else 'Link olib boʻlmadi'}")

# ── Statistika, Reklama va boshqa funksiyalar (O'zgarishsiz qoldi) ─────────────

@router.callback_query(F.data == "list_channels")
async def list_channels(call: CallbackQuery):
    channels = db.get_all_channels()
    if not channels:
        return await call.answer("Bazada kanallar yo'q.", show_alert=True)
    text = "📋 <b>Kanallar ro'yxati:</b>\n\n"
    kb_list = []
    for ch in channels:
        text += f"🔹 {ch['channel_title']} (@{ch['channel_username']})\n"
        if call.from_user.id == config.ADMIN_ID:
            kb_list.append([InlineKeyboardButton(text=f"🗑 {ch['channel_title']}", callback_data=f"del_{ch['channel_id']}")])
    kb_list.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_start")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@router.callback_query(F.data.startswith("del_"))
async def delete_channel(call: CallbackQuery):
    ch_id = int(call.data.split("_")[1])
    db.remove_channel(ch_id)
    await call.answer("✅ O'chirildi.")
    await list_channels(call)

@router.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery):
    await call.message.answer(f"📊 Foydalanuvchilar: {db.get_user_count()}\n📢 Kanallar: {db.get_channel_count()}")
    await call.answer()

@router.callback_query(F.data == "broadcast")
async def start_broadcast(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📝 Reklama yuboring:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    users = db.get_all_user_ids()
    count = 0
    for u_id in users:
        try:
            await message.copy_to(u_id)
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    await message.answer(f"✅ {count} ta odamga yuborildi.")

@router.callback_query(F.data == "back_start")
async def back_to_start(call: CallbackQuery):
    await call.message.delete()
    await cmd_start(call.message)