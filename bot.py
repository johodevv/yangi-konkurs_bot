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

# ── FSM Holatlari ─────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Konkurs jildi (folder) yaratuvchi botga xush kelibsiz.\n"
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

# ── Kanal qo'shish (To'g'rilangan variant) ───────────────────────────────────

@router.message(F.text.contains("t.me/") | F.text.startswith("@"))
async def handle_link(message: Message):
    if message.from_user.id != config.ADMIN_ID:
        return

    text = message.text.strip()
    # Linkdan username ajratishni yaxshilaymiz
    username = text.split('/')[-1].replace("@", "").split('?')[0]
    
    msg = await message.answer("🔍 Kanal tekshirilmoqda...")
    try:
        chat = await bot.get_chat(f"@{username}")
        db.add_channel(chat.id, chat.username, chat.title, text)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_{chat.id}")]
        ])
        await msg.edit_text(
            f"✅ <b>{chat.title}</b> bazaga qo'shildi!\n\n"
            f"❗️ Bot ushbu kanalda admin bo'lishi shart.", 
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Kanal xatosi: {e}")
        await msg.edit_text("❌ Kanal topilmadi. Botni kanalga admin qilib, so'ng username yuboring.")

# ── Jild Linkini olish (Asosiy xato shu yerda edi) ────────────────────────────

@router.callback_query(F.data == "get_link")
async def send_folder_link(call: CallbackQuery):
    # 'userbot' obyekti bot.py ichidagi global o'zgaruvchi ekanini funksiyaga aytamiz
    import bot as bot_module 
    ub = bot_module.userbot

    if ub is None:
        return await call.answer("⚠️ UserBot hali ulanmagan. Bir ozdan so'ng qayta urining.", show_alert=True)
    
    await call.message.edit_text("⏳ Jild linki tayyorlanmoqda, kuting...")
    
    try:
        # userbot.py dagi funksiyani chaqiramiz
        link = await ub.create_folder_link()
        
        if link:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Jildga qo'shilish", url=link)]
            ])
            await call.message.answer(
                f"📂 <b>Konkurs jildi tayyor!</b>\n\n"
                f"Link: <code>{link}</code>",
                reply_markup=kb
            )
            await call.message.delete()
        else:
            await call.message.answer("❌ Jild yaratib bo'lmadi. Kanallar bazada borligini tekshiring.")
    except Exception as e:
        logger.error(f"Folder xatosi: {e}")
        await call.message.answer(f"❌ Xatolik: {str(e)}")

# ── Kanallar ro'yxati ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "list_channels")
async def list_channels(call: CallbackQuery):
    channels = db.get_all_channels()
    if not channels:
        return await call.answer("Bazada kanallar yo'q.", show_alert=True)

    text = "📋 <b>Bazadagi kanallar:</b>\n\n"
    kb_list = []
    for ch in channels:
        # SQLite'dan kelayotgan formatni tekshiramiz (dict yoki list)
        title = ch['channel_title'] if isinstance(ch, dict) else ch[3]
        username = ch['channel_username'] if isinstance(ch, dict) else ch[2]
        ch_id = ch['channel_id'] if isinstance(ch, dict) else ch[1]
        
        text += f"🔹 {title} (@{username})\n"
        if call.from_user.id == config.ADMIN_ID:
            kb_list.append([InlineKeyboardButton(text=f"🗑 {title}", callback_data=f"del_{ch_id}")])

    kb_list.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_start")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

# ── Kanalni o'chirish ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("del_"))
async def delete_channel(call: CallbackQuery):
    ch_id = int(call.data.split("_")[1])
    db.remove_channel(ch_id)
    await call.answer("✅ Kanal o'chirildi.")
    await list_channels(call)

# ── Statistika va Reklama (Asl holicha saqlandi) ───────────────────────────────

@router.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery):
    if call.from_user.id != config.ADMIN_ID: return
    await call.message.answer(f"📊 Foydalanuvchilar: {db.get_user_count()}\n📢 Kanallar: {db.get_channel_count()}")
    await call.answer()

@router.callback_query(F.data == "broadcast")
async def start_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != config.ADMIN_ID: return
    await call.message.answer("📝 Reklama xabarini yuboring:")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await call.answer()

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
    await message.answer(f"✅ Reklama {count} ta foydalanuvchiga yuborildi.")

@router.callback_query(F.data == "back_start")
async def back_to_start(call: CallbackQuery):
    await call.message.delete()
    await cmd_start(call.message)