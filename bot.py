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

# Global userbot referensi (main.py tomonidan o'rnatiladi)
userbot = None


# ── FSM Holatlari ─────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_channel    = State()   # kanal linki kutilmoqda
    waiting_broadcast  = State()   # reklama xabari kutilmoqda


# ── Yordamchi funksiyalar ─────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


def make_join_keyboard(folder_link: str) -> InlineKeyboardMarkup:
    """'Jildga qo'shilish' tugmali inline klaviatura."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📁 Jildga qo'shilish",
            url=folder_link
        )
    ]])


async def get_bot_channel_link(channel_id: int) -> str | None:
    """
    Kanal uchun invite link oladi.
    Bot adminda bo'lishi va invite_link huquqi bo'lishi kerak.
    """
    try:
        chat = await bot.get_chat(channel_id)
        if chat.invite_link:
            return chat.invite_link
        # Yangi link yaratish
        link = await bot.create_chat_invite_link(channel_id)
        return link.invite_link
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.error(f"Link olishda xatolik ({channel_id}): {e}")
        return None
    except Exception as e:
        logger.error(f"Kutilmagan xatolik ({channel_id}): {e}")
        return None


async def check_bot_is_admin(channel_id: int) -> bool:
    """Bot o'sha kanalda admin ekanligini tekshiradi."""
    try:
        member = await bot.get_chat_member(channel_id, (await bot.get_me()).id)
        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    except Exception as e:
        logger.error(f"Admin tekshirishda xatolik: {e}")
        return False


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    try:
        db.add_user(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name or "",
        )

        if is_admin(message.from_user.id):
            await message.answer(
                "👋 <b>Salom, Admin!</b>\n\n"
                "📋 <b>Buyruqlar:</b>\n"
                "➕ /add_channel — kanal qo'shish\n"
                "📋 /channels — kanallar ro'yxati\n"
                "🔗 /get_folder — jild linkini olish\n"
                "📢 /broadcast — reklama yuborish\n"
                "📊 /stats — statistika"
            )
        else:
            channel_count = db.get_channel_count()
            await message.answer(
                f"👋 <b>Xush kelibsiz!</b>\n\n"
                f"Bu bot <b>{channel_count} ta</b> konkurs kanalini "
                f"bitta jildda jamlaydi.\n\n"
                f"Jildga qo'shilish uchun /get_folder buyrug'ini yuboring."
            )
    except Exception as e:
        logger.error(f"cmd_start xatolik: {e}")


# ── /add_channel ──────────────────────────────────────────────────────────────

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminStates.waiting_channel)
    await message.answer(
        "📨 <b>Kanal username yoki ID ni yuboring:</b>\n\n"
        "Misol: <code>@mening_kanalim</code>\n"
        "yoki: <code>-1001234567890</code>\n\n"
        "❌ Bekor qilish: /cancel"
    )


@router.message(AdminStates.waiting_channel)
async def process_channel_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    text = message.text.strip() if message.text else ""

    # /cancel
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    try:
        chat = await bot.get_chat(text)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer(
            "⚠️ <b>Kanal topilmadi!</b>\n\n"
            "Tekshiring:\n"
            "• Username to'g'ri ekanligini\n"
            "• Bot kanalga qo'shilganligini\n\n"
            "Qaytadan yuboring yoki /cancel"
        )
        return
    except Exception as e:
        logger.error(f"get_chat xatolik: {e}")
        await message.answer(f"⚠️ Xatolik: <code>{e}</code>\n\nQaytadan urinib ko'ring.")
        return

    # Bot admin ekanligini tekshirish
    is_bot_admin = await check_bot_is_admin(chat.id)
    if not is_bot_admin:
        await state.clear()
        await message.answer(
            f"❌ <b>Bot kanalda admin emas!</b>\n\n"
            f"Kanal: <b>{chat.title}</b>\n\n"
            f"Avval botni kanalga admin qilib qo'ying, keyin qaytadan urinib ko'ring."
        )
        return

    # Allaqachon bazada bormi?
    if db.channel_exists(chat.id):
        await state.clear()
        await message.answer(
            f"⚠️ <b>{chat.title}</b> allaqachon bazada mavjud!"
        )
        return

    # Invite link olish
    invite_link = await get_bot_channel_link(chat.id)

    username = f"@{chat.username}" if chat.username else ""
    success = db.add_channel(chat.id, username, chat.title, invite_link)

    await state.clear()

    if success:
        await message.answer(
            f"✅ <b>Kanal qo'shildi!</b>\n\n"
            f"📌 Nomi: <b>{chat.title}</b>\n"
            f"🆔 ID: <code>{chat.id}</code>\n"
            f"👤 Username: {username or 'yo`q'}\n\n"
            f"Jami kanallar: <b>{db.get_channel_count()} ta</b>"
        )
    else:
        await message.answer("❌ Bazaga saqlashda xatolik yuz berdi.")


# ── /channels ─────────────────────────────────────────────────────────────────

@router.message(Command("channels"))
async def cmd_channels(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        channels = db.get_channels()
        if not channels:
            await message.answer("📋 Bazada hozircha kanallar yo'q.")
            return

        lines = [f"📋 <b>Kanallar ro'yxati ({len(channels)} ta):</b>\n"]
        for i, (ch_id, ch_username, ch_title, _) in enumerate(channels, 1):
            username_str = ch_username if ch_username else "username yo`q"
            lines.append(f"{i}. <b>{ch_title}</b> ({username_str})\n   ID: <code>{ch_id}</code>")

        await message.answer("\n".join(lines))
    except Exception as e:
        logger.error(f"cmd_channels xatolik: {e}")
        await message.answer("⚠️ Xatolik yuz berdi.")


# ── /get_folder ───────────────────────────────────────────────────────────────

@router.message(Command("get_folder"))
async def cmd_get_folder(message: Message):
    try:
        if db.get_channel_count() == 0:
            await message.answer("⚠️ Bazada hozircha kanallar yo'q.")
            return

        wait_msg = await message.answer("⏳ Jild linki yaratilmoqda…")

        if userbot is None or not userbot.is_ready:
            await wait_msg.delete()
            await message.answer(
                "⚠️ <b>UserBot hozir ishlamayapti.</b>\n\n"
                "SESSION_STRING to'g'ri o'rnatilganligini tekshiring."
            )
            return

        folder_link = await userbot.create_folder_link()
        await wait_msg.delete()

        if folder_link:
            await message.answer(
                f"✅ <b>Jild linki tayyor!</b>\n\n"
                f"🔗 {folder_link}\n\n"
                f"Bu link orqali barcha konkurs kanallarini\n"
                f"bir jildda qabul qilasiz!",
                reply_markup=make_join_keyboard(folder_link)
            )
        else:
            await message.answer(
                "❌ <b>Jild linki yaratishda xatolik.</b>\n\n"
                "Loglarni tekshiring."
            )
    except Exception as e:
        logger.error(f"cmd_get_folder xatolik: {e}")
        await message.answer("⚠️ Xatolik yuz berdi.")


# ── /stats ────────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        await message.answer(
            f"📊 <b>Statistika:</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
            f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>"
        )
    except Exception as e:
        logger.error(f"cmd_stats xatolik: {e}")


# ── /broadcast ────────────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if db.get_channel_count() == 0:
        await message.answer("⚠️ Bazada kanallar yo'q. Avval kanal qo'shing.")
        return

    await state.set_state(AdminStates.waiting_broadcast)
    await message.answer(
        "📢 <b>Reklama xabarini yuboring:</b>\n\n"
        "Xabar avtomatik ravishda bazadagi barcha kanallarga\n"
        "\"Jildga qo'shilish\" tugmasi bilan yuboriladi.\n\n"
        "❌ Bekor qilish: /cancel"
    )


@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    await state.clear()

    # Folder link olish
    folder_link = None
    if userbot and userbot.is_ready:
        wait_msg = await message.answer("⏳ Jild linki olinmoqda…")
        folder_link = await userbot.create_folder_link()
        try:
            await wait_msg.delete()
        except Exception:
            pass

    keyboard = make_join_keyboard(folder_link) if folder_link else None

    channels = db.get_channels()
    success_count = 0
    fail_count = 0

    progress_msg = await message.answer(
        f"📤 Yuborilmoqda: 0/{len(channels)}"
    )

    for i, (ch_id, _, ch_title, _) in enumerate(channels, 1):
        try:
            await bot.copy_message(
                chat_id=ch_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            success_count += 1
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning(f"Kanalga yuborishda xatolik ({ch_title}): {e}")
            fail_count += 1
        except Exception as e:
            logger.error(f"Kutilmagan xatolik ({ch_title}): {e}")
            fail_count += 1

        # Har 5 ta kanaldan keyin progress yangilash
        if i % 5 == 0:
            try:
                await progress_msg.edit_text(
                    f"📤 Yuborilmoqda: {i}/{len(channels)}"
                )
            except Exception:
                pass

        await asyncio.sleep(0.1)  # flood limitdan saqlanish

    try:
        await progress_msg.delete()
    except Exception:
        pass

    await message.answer(
        f"✅ <b>Reklama yuborildi!</b>\n\n"
        f"✔️ Muvaffaqiyatli: <b>{success_count} ta</b>\n"
        f"❌ Xatolik: <b>{fail_count} ta</b>"
    )


# ── /cancel (global) ──────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
    else:
        await message.answer("⚠️ Hozir aktiv jarayon yo'q.")


# ── Noma'lum xabarlar ─────────────────────────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_unknown(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        return  # FSM holati bor — tegishli handler ishlasin

    if is_admin(message.from_user.id):
        await message.answer(
            "❓ Buyruqni tanlamadingiz.\n\n"
            "/add_channel, /channels, /get_folder, /broadcast, /stats"
        )
