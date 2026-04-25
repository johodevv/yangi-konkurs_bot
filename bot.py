import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
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

# Global userbot referensi (main.py dan keladi)
userbot = None

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# ── /start ────────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    welcome_text = "👋 <b>Assalomu alaykum!</b>\n\nJild (folder) botiga xush kelibsiz."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanallar", callback_data="list_channels"),
         InlineKeyboardButton(text="📂 Jild Linki", callback_data="get_link")]
    ])
    if message.from_user.id == config.ADMIN_ID:
        kb.inline_keyboard.append([InlineKeyboardButton(text="📊 Stats", callback_data="stats"),
                                   InlineKeyboardButton(text="✉️ Reklama", callback_data="broadcast")])
    await message.answer(welcome_text, reply_markup=kb)

# ── Kanal qo'shish (Tuzatildi) ──────────────────────────────────────────────────
@router.message(F.text.contains("t.me/") | F.text.startswith("@"))
async def handle_link(message: Message):
    if message.from_user.id != config.ADMIN_ID: return
    username = message.text.strip().split('/')[-1].replace("@", "").split('?')[0]
    msg = await message.answer("🔍 Tekshirilmoqda...")
    try:
        chat = await bot.get_chat(f"@{username}")
        db.add_channel(chat.id, chat.username, chat.title, message.text.strip())
        await msg.edit_text(f"✅ <b>{chat.title}</b> qo'shildi!")
    except Exception:
        await msg.edit_text("❌ Kanal topilmadi yoki bot admin emas.")

# ── Jild Linki (Xato tuzatilgan joyi) ──────────────────────────────────────────
@router.callback_query(F.data == "get_link")
async def send_folder_link(call: CallbackQuery):
    # bot.py dagi userbot obyektini to'g'ri olish
    import bot as bot_module
    ub = bot_module.userbot

    if ub is None:
        return await call.answer("⚠️ UserBot hali ulanmagan, biroz kuting...", show_alert=True)
    
    await call.message.edit_text("⏳ Link tayyorlanmoqda...")
    link = await ub.create_folder_link()
    
    if link:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Kirish", url=link)]])
        await call.message.answer(f"📂 <b>Jild tayyor:</b>\n{link}", reply_markup=kb)
    else:
        await call.message.answer("❌ Link olib bo'lmadi. Bazani tekshiring.")

# ── Boshqa funksiyalar (Asl holicha) ──────────────────────────────────────────
@router.callback_query(F.data == "list_channels")
async def list_channels(call: CallbackQuery):
    channels = db.get_all_channels()
    if not channels: return await call.answer("Baza bo'sh.")
    text = "📋 Kanallar:\n\n"
    kb = []
    for ch in channels:
        text += f"🔹 {ch['channel_title']}\n"
        if call.from_user.id == config.ADMIN_ID:
            kb.append([InlineKeyboardButton(text=f"🗑 {ch['channel_title']}", callback_data=f"del_{ch['channel_id']}")])
    kb.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("del_"))
async def delete_ch(call: CallbackQuery):
    db.remove_channel(int(call.data.split("_")[1]))
    await call.answer("O'chirildi.")
    await list_channels(call)

@router.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery):
    await call.message.answer(f"👤 Users: {db.get_user_count()}\n📢 Kanallar: {db.get_channel_count()}")

@router.callback_query(F.data == "broadcast")
async def start_br(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Xabarni yuboring:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def proc_br(message: Message, state: FSMContext):
    await state.clear()
    users = db.get_all_user_ids()
    for u_id in users:
        try: await message.copy_to(u_id); await asyncio.sleep(0.05)
        except: continue
    await message.answer("✅ Tayyor.")

@router.callback_query(F.data == "back")
async def go_back(call: CallbackQuery):
    await call.message.delete(); await cmd_start(call.message)