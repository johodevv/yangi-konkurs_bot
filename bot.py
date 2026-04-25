import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import config
import database as db

logger = logging.getLogger(__name__)
bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

userbot = None # main.py orqali ulanadi

class AddChannel(StatesGroup):
    waiting_for_link = State()
    waiting_for_admin_check = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# ── Start ──
@router.message(CommandStart())
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_my_channel")],
        [InlineKeyboardButton(text="📂 Jild Linki", callback_data="get_link")]
    ])
    if message.from_user.id == config.ADMIN_ID:
        kb.inline_keyboard.append([InlineKeyboardButton(text="📊 Stats", callback_data="stats"),
                                   InlineKeyboardButton(text="✉️ Reklama", callback_data="broadcast")])
    
    await message.answer("Xush kelibsiz! O'z kanalingizni konkurs jildiga qo'shishingiz mumkin.", reply_markup=kb)

# ── Kanal qo'shish jarayoni ──
@router.callback_query(F.data == "add_my_channel")
async def start_add_channel(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Kanal linkini yuboring (masalan: @username yoki t.me/link):")
    await state.set_state(AddChannel.waiting_for_link)

@router.message(AddChannel.waiting_for_link)
async def process_link(message: Message, state: FSMContext):
    link = message.text.strip()
    username = link.split('/')[-1].replace("@", "").split('?')[0]
    
    try:
        chat = await bot.get_chat(f"@{username}")
        await state.update_data(ch_id=chat.id, ch_title=chat.title, ch_username=chat.username, ch_link=link)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Admin qildim", callback_data="check_admin")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_start")]
        ])
        await message.answer(f"Kanal: <b>{chat.title}</b>\n\nEndi botni ushbu kanalga <b>admin</b> qiling va pastdagi tugmani bosing.", reply_markup=kb)
        await state.set_state(AddChannel.waiting_for_admin_check)
    except Exception:
        await message.answer("❌ Kanal topilmadi. Linkni to'g'ri yuboring.")

@router.callback_query(F.data == "check_admin")
async def check_admin_status(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ch_id = data.get("ch_id")
    
    try:
        member = await bot.get_chat_member(ch_id, (await bot.get_me()).id)
        if member.status in ["administrator", "creator"]:
            db.add_channel(ch_id, data['ch_username'], data['ch_title'], data['ch_link'])
            await call.message.edit_text(f"✅ Tabriklaymiz! <b>{data['ch_title']}</b> jildga qo'shildi.")
            await state.clear()
        else:
            await call.answer("❌ Bot hali kanalingizda admin emas!", show_alert=True)
    except Exception:
        await call.answer("❌ Botni kanalga qo'shing va admin huquqini bering!", show_alert=True)

# ── Jild Linki ──
@router.callback_query(F.data == "get_link")
async def send_link(call: CallbackQuery):
    import bot as bot_module
    ub = bot_module.userbot
    if not ub: return await call.answer("UserBot ulanmagan.", show_alert=True)
    
    await call.message.edit_text("⏳ Link tayyorlanmoqda...")
    link = await ub.create_folder_link()
    if link:
        await call.message.answer(f"📂 Jild tayyor: {link}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Kirish", url=link)]
        ]))
    else:
        await call.message.answer("❌ Xato! Bazada kanal yo'q bo'lishi mumkin.")

# ── Statistika va Reklama (Asl holicha) ──
@router.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    await call.message.answer(f"Foydalanuvchilar: {db.get_user_count()}\nKanallar: {db.get_channel_count()}")

@router.callback_query(F.data == "broadcast")
async def br_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Xabarni yuboring:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def br_proc(message: Message, state: FSMContext):
    await state.clear()
    users = db.get_all_user_ids()
    for u_id in users:
        try: await message.copy_to(u_id); await asyncio.sleep(0.05)
        except: continue
    await message.answer("Tayyor.")

@router.callback_query(F.data == "back_start")
async def back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await cmd_start(call.message)