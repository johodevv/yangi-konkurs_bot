"""
bot.py — Konkurs Jild Boti (Aiogram 3.x)

Kanal egasi flow:
  /start → majburiy obuna → kanal link → admin berish → jildga qo'shish

Admin flow:
  /admin → panel → reklama (jild tugmasi bilan barcha kanallarga)
"""

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

logger  = logging.getLogger(__name__)
bot     = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp      = Dispatcher(storage=storage)
router  = Router()
dp.include_router(router)

# UserBot — main.py tomonidan o'rnatiladi
userbot = None


# ═══════════════════════════════════════════════════════════
#  FSM
# ═══════════════════════════════════════════════════════════

class UserFlow(StatesGroup):
    waiting_channel_link = State()
    waiting_admin_check  = State()

class AdminFlow(StatesGroup):
    waiting_broadcast = State()


# ═══════════════════════════════════════════════════════════
#  KLAVIATURALAR
# ═══════════════════════════════════════════════════════════

def kb_subscribe() -> InlineKeyboardMarkup:
    rows = []
    for ch in config.REQUIRED:
        emoji = "📢" if ch["type"] == "kanal" else "👥"
        rows.append([InlineKeyboardButton(
            text=f"{emoji} {ch['title']} ({ch['type']})",
            url=ch["url"]
        )])
    rows.append([InlineKeyboardButton(
        text="✅ Obuna bo'ldim — Tekshir",
        callback_data="check_sub"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_admin_grant(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📖 Admin berish qo'llanmasi",
            url=f"https://t.me/{bot_username}"
        )],
        [InlineKeyboardButton(
            text="✅ Admin berdim, kanalimni qo'sh!",
            callback_data="admin_given"
        )],
    ])


def kb_folder(folder_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📁 Jildga qo'shilish", url=folder_link)
    ]])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Konkursni boshlash (Reklama)", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Statistika",                   callback_data="admin_stats")],
        [InlineKeyboardButton(text="📋 Kanallar ro'yxati",            callback_data="admin_channels")],
        [InlineKeyboardButton(text="🔗 Jild linkini yangilash",       callback_data="admin_folder")],
    ])


# ═══════════════════════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid == config.ADMIN_ID


def is_cancel(text: str | None) -> bool:
    """'/cancel' yoki '/cancel@botusername' formatini tekshiradi."""
    if not text:
        return False
    cmd = text.strip().split("@")[0].lower()
    return cmd == "/cancel"


async def get_not_subscribed(user_id: int) -> list:
    result = []
    for ch in config.REQUIRED:
        try:
            m = await bot.get_chat_member(f"@{ch['username']}", user_id)
            if m.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.BANNED,
                ChatMemberStatus.KICKED,
            ):
                result.append(ch)
        except Exception:
            # Bot kanalda admin emas yoki kanal topilmadi — skip
            pass
    return result


async def check_bot_admin(channel_id: int) -> bool:
    try:
        me = await bot.get_me()
        m  = await bot.get_chat_member(channel_id, me.id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        return False


async def get_invite_link(channel_id: int) -> str | None:
    try:
        chat = await bot.get_chat(channel_id)
        if chat.invite_link:
            return chat.invite_link
        lnk = await bot.create_chat_invite_link(channel_id)
        return lnk.invite_link
    except Exception as e:
        logger.error(f"Invite link xatolik ({channel_id}): {e}")
        return None


async def get_folder_link() -> str | None:
    """UserBot orqali jild linkini oladi yoki None qaytaradi."""
    if userbot and userbot.is_ready:
        return await userbot.create_folder_link()
    return None


# ═══════════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    db.add_user(
        msg.from_user.id,
        msg.from_user.username or "",
        msg.from_user.full_name or "",
    )

    if is_admin(msg.from_user.id):
        await msg.answer(
            "👋 <b>Salom, Admin!</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
            f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>\n\n"
            "Quyidagi tugmalardan birini tanlang:",
            reply_markup=kb_admin_panel()
        )
        return

    # Majburiy obuna tekshirish
    not_sub = await get_not_subscribed(msg.from_user.id)
    if not_sub:
        names = " va ".join(
            f"<b>{ch['title']}</b> ({ch['type']})" for ch in not_sub
        )
        await msg.answer(
            "👋 <b>Botga xush kelibsiz!</b>\n\n"
            f"⚠️ Botdan foydalanish uchun {names}ga "
            f"obuna bo'lishingiz <b>shart</b>.\n\n"
            "Obuna bo'lgach ✅ tugmasini bosing 👇",
            reply_markup=kb_subscribe()
        )
        return

    await _ask_channel_link(msg, state, msg.from_user.id)


# ═══════════════════════════════════════════════════════════
#  OBUNA TEKSHIRISH CALLBACK
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery, state: FSMContext):
    not_sub = await get_not_subscribed(call.from_user.id)

    if not_sub:
        names = ", ".join(ch["title"] for ch in not_sub)
        await call.answer(
            f"❌ Hali {names}ga obuna bo'lmagansiz!",
            show_alert=True
        )
        return

    await call.answer("✅ Obuna tasdiqlandi!", show_alert=False)

    try:
        await call.message.delete()
    except Exception:
        pass

    await _ask_channel_link(call.message, state, call.from_user.id)


# ═══════════════════════════════════════════════════════════
#  KANAL LINKI SO'RASH (ichki funksiya)
# ═══════════════════════════════════════════════════════════

async def _ask_channel_link(msg: Message, state: FSMContext, user_id: int):
    await state.set_state(UserFlow.waiting_channel_link)
    await state.update_data(user_id=user_id)

    await msg.answer(
        "🎉 <b>Ajoyib! Obuna tasdiqlandi.</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 <b>Kanalingiz username yoki linkini yuboring</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Misol:</b>\n"
        "• <code>@mening_kanalim</code>\n"
        "• <code>https://t.me/mening_kanalim</code>\n\n"
        "💡 <i>Kanal public bo'lishi yoki botga admin huquqi "
        "berilgan bo'lishi kerak.</i>\n\n"
        "❌ Bekor qilish: /cancel"
    )


# ═══════════════════════════════════════════════════════════
#  KANAL LINKI QABUL QILISH
# ═══════════════════════════════════════════════════════════

@router.message(UserFlow.waiting_channel_link)
async def process_channel_link(msg: Message, state: FSMContext):
    if not msg.text:
        await msg.answer("⚠️ Iltimos, kanal username yoki linkini yuboring.")
        return

    text = msg.text.strip()

    # Buyruqlarni tutib qolish
    if text.startswith("/"):
        if is_cancel(text):
            await state.clear()
            await msg.answer("❌ Bekor qilindi. Qaytadan boshlash: /start")
        else:
            await msg.answer(
                "⚠️ Avval kanal linkini yuboring yoki bekor qilish uchun /cancel bosing."
            )
        return

    # t.me/username → @username
    if "t.me/" in text and "+=" not in text:
        text = "@" + text.split("t.me/")[-1].strip("/").split("?")[0]

    # Kanalni Telegram orqali tekshirish
    try:
        chat = await bot.get_chat(text)
    except (TelegramBadRequest, TelegramForbiddenError):
        await msg.answer(
            "❌ <b>Kanal topilmadi!</b>\n\n"
            "Tekshiring:\n"
            "• Username to'g'ri yozilganmi?\n"
            "• Kanal public ekanmi?\n\n"
            "Qaytadan yuboring yoki /cancel:"
        )
        return
    except Exception as e:
        logger.error(f"get_chat xatolik: {e}")
        await msg.answer("⚠️ Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        return

    # Allaqachon bazada bormi?
    if db.channel_exists(chat.id):
        await msg.answer(
            f"⚠️ <b>{chat.title}</b> kanali allaqachon jildda mavjud!\n\n"
            "Boshqa kanal linki yuboring yoki /cancel."
        )
        return

    # Kanal ma'lumotlarini FSM ga saqlash
    await state.update_data(
        channel_id=chat.id,
        channel_title=chat.title,
        channel_username=f"@{chat.username}" if chat.username else "",
    )
    await state.set_state(UserFlow.waiting_admin_check)

    me = await bot.get_me()

    await msg.answer(
        f"✅ <b>Kanal topildi!</b>\n\n"
        f"📌 Kanal: <b>{chat.title}</b>\n"
        f"👤 Username: <code>@{chat.username or 'private'}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Endi botga admin bering</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kanalingizni jildga qo'shish uchun botga "
        "<b>admin huquqi</b> berilishi shart.\n\n"
        "<b>Qadamlar:</b>\n"
        "1️⃣ Kanalingizga kiring\n"
        "2️⃣ Sozlamalar → Adminlar → Admin qo'shish\n"
        f"3️⃣ <code>@{me.username}</code> ni qidiring\n"
        "4️⃣ Qo'shib, huquqlarni tasdiqlang\n"
        "5️⃣ Pastdagi ✅ tugmani bosing 👇",
        reply_markup=kb_admin_grant(me.username)
    )


# ═══════════════════════════════════════════════════════════
#  ADMIN BERILDI CALLBACK
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_given")
async def cb_admin_given(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    channel_id    = data.get("channel_id")
    channel_title = data.get("channel_title", "Noma'lum")
    channel_user  = data.get("channel_username", "")

    if not channel_id:
        await call.answer(
            "⚠️ Seans tugagan. Qaytadan /start bosing.",
            show_alert=True
        )
        await state.clear()
        return

    # Bot admin ekanligini tekshirish
    if not await check_bot_admin(channel_id):
        await call.answer(
            "❌ Bot hali admin emas!\n\n"
            "Kanalga admin qilib qo'ying va qayta bosing.",
            show_alert=True
        )
        return

    # Faqat 1 marta call.answer — bu yerda
    await call.answer("⏳ Kanalingiz qo'shilmoqda...", show_alert=False)

    # Invite link olish
    invite_link = await get_invite_link(channel_id)

    # Bazaga saqlash
    uid = data.get("user_id") or call.from_user.id
    success = db.add_channel(channel_id, channel_user, channel_title, invite_link, uid)

    if not success:
        await call.message.edit_text(
            "❌ <b>Bazaga saqlashda xatolik yuz berdi.</b>\n\n"
            "Qaytadan urinib ko'ring: /start"
        )
        await state.clear()
        return

    await state.clear()

    # Jild linkini olish (UserBot)
    folder_link = await get_folder_link()

    if folder_link:
        await call.message.edit_text(
            f"🎊 <b>Tabriklaymiz!</b>\n\n"
            f"✅ <b>{channel_title}</b> muvaffaqiyatli jildga qo'shildi!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📁 Barcha konkurs kanallarini bitta jildda ko'rish uchun "
            "quyidagi tugmani bosing 👇",
            reply_markup=kb_folder(folder_link)
        )
    else:
        await call.message.edit_text(
            f"✅ <b>{channel_title}</b> bazaga qo'shildi!\n\n"
            "📁 Jild linki tez orada tayyorlanadi.\n"
            "Admin bilan bog'laning."
        )

    # Adminga bildirishnoma
    try:
        await bot.send_message(
            config.ADMIN_ID,
            f"🆕 <b>Yangi kanal qo'shildi!</b>\n\n"
            f"📌 Kanal: <b>{channel_title}</b>\n"
            f"👤 Username: {channel_user or 'private'}\n"
            f"👤 Egasi: {('@' + call.from_user.username) if call.from_user.username else str(call.from_user.id)}\n\n"
            f"📊 Jami kanallar: <b>{db.get_channel_count()} ta</b>"
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  ADMIN PANEL — /admin buyrug'i
# ═══════════════════════════════════════════════════════════

@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer(
        f"🛠 <b>Admin Panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
        f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>",
        reply_markup=kb_admin_panel()
    )


# ═══════════════════════════════════════════════════════════
#  ADMIN PANEL — CALLBACKLAR
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    await call.message.edit_text(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
        f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back")
        ]])
    )


@router.callback_query(F.data == "admin_channels")
async def cb_admin_channels(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()

    channels = db.get_channels()
    if not channels:
        await call.message.edit_text(
            "📋 <b>Hozircha kanallar yo'q.</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back")
            ]])
        )
        return

    lines = [f"📋 <b>Kanallar ({len(channels)} ta):</b>\n"]
    for i, (ch_id, ch_user, ch_title, _) in enumerate(channels, 1):
        uname = ch_user if ch_user else "private"
        lines.append(f"{i}. <b>{ch_title}</b> — {uname}")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back")
        ]])
    )


@router.callback_query(F.data == "admin_folder")
async def cb_admin_folder(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return

    # call.answer() faqat bitta path da chaqirilishi kerak
    if not userbot or not userbot.is_ready:
        await call.answer(
            "❌ UserBot ishlamayapti!\nSESSION_STRING ni tekshiring.",
            show_alert=True
        )
        return

    await call.answer("⏳ Jild linki yangilanmoqda...", show_alert=False)

    folder_link = await userbot.create_folder_link()
    if folder_link:
        await call.message.answer(
            f"✅ <b>Jild linki yangilandi!</b>\n\n"
            f"🔗 {folder_link}",
            reply_markup=kb_folder(folder_link)
        )
    else:
        await call.message.answer(
            "❌ <b>Jild linki olinmadi.</b>\n\n"
            "Kanallar bazada borligini va UserBot ulangan-"
            "ligini tekshiring."
        )


@router.callback_query(F.data == "admin_back")
async def cb_admin_back(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    await call.message.edit_text(
        f"🛠 <b>Admin Panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
        f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>",
        reply_markup=kb_admin_panel()
    )


# ═══════════════════════════════════════════════════════════
#  REKLAMA TARQATISH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return

    if db.get_channel_count() == 0:
        await call.answer("❌ Bazada kanallar yo'q!", show_alert=True)
        return

    # call.answer() AVVAL chaqiriladi (30s timeout xavfini oldini olish)
    await call.answer()

    await state.set_state(AdminFlow.waiting_broadcast)
    await call.message.edit_text(
        "📢 <b>Konkurs xabarini yuboring</b>\n\n"
        "Xabar bazadagi barcha kanallarga avtomatik "
        "\"📁 Jildga qo'shilish\" tugmasi bilan yuboriladi.\n\n"
        "📝 Matn, rasm, video — barchasi qabul qilinadi.\n\n"
        "❌ Bekor qilish: /cancel",
        reply_markup=None
    )


@router.message(AdminFlow.waiting_broadcast)
async def process_broadcast(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return

    # /cancel va boshqa buyruqlarni tutib qolish
    if msg.text and msg.text.startswith("/"):
        if is_cancel(msg.text):
            await state.clear()
            await msg.answer("❌ Bekor qilindi.", reply_markup=kb_admin_panel())
        else:
            await msg.answer(
                "⚠️ Avval xabar yuboring yoki /cancel bosing."
            )
        return

    await state.clear()

    # Jild linkini olish
    folder_link = None
    wait_msg = await msg.answer("⏳ Jild linki olinmoqda...")
    try:
        folder_link = await get_folder_link()
    except Exception as e:
        logger.error(f"Jild linki xatolik: {e}")
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass

    # Keyboard — jild linki bo'lsa tugma, bo'lmasa None
    keyboard = kb_folder(folder_link) if folder_link else None

    if not folder_link:
        logger.warning("Broadcast: jild linki yo'q — tugmasiz yuboriladi.")

    channels = db.get_channels()
    total    = len(channels)
    ok       = 0
    fail     = 0

    prog_msg = await msg.answer(f"📤 Yuborilmoqda: 0 / {total}")

    for i, (ch_id, _, ch_title, _) in enumerate(channels, 1):
        try:
            await bot.copy_message(
                chat_id=ch_id,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id,
                reply_markup=keyboard,
                # parse_mode bu yerda ishlatilmaydi:
                # copy_message originalning formatini saqlaydi.
            )
            ok += 1
        except TelegramForbiddenError:
            # Bot kanaldan chiqarilgan
            logger.warning(f"Bot kanaldan chiqarilgan: {ch_title} — bazadan o'chirilmoqda")
            db.remove_channel(ch_id)
            fail += 1
        except TelegramBadRequest as e:
            logger.warning(f"BadRequest ({ch_title}): {e}")
            fail += 1
        except Exception as e:
            logger.error(f"Yuborish xatolik ({ch_title}): {e}")
            fail += 1

        # Har 5 ta kanalda progress yangilash
        if i % 5 == 0:
            try:
                await prog_msg.edit_text(f"📤 Yuborilmoqda: {i} / {total}")
            except Exception:
                pass

        # Flood limitdan saqlanish — 0.3s oraliq
        await asyncio.sleep(0.3)

    try:
        await prog_msg.delete()
    except Exception:
        pass

    status = (
        f"✅ <b>Reklama yuborildi!</b>\n\n"
        f"✔️ Muvaffaqiyatli: <b>{ok} ta</b>\n"
        f"❌ Xatolik: <b>{fail} ta</b>"
    )
    if not folder_link:
        status += "\n\n⚠️ Jild linki olinmadi — tugmasiz yuborildi."

    await msg.answer(status, reply_markup=kb_admin_panel())


# ═══════════════════════════════════════════════════════════
#  /cancel — global
# ═══════════════════════════════════════════════════════════

@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await msg.answer("❌ Bekor qilindi. /start bilan qaytadan boshlang.")
    else:
        await msg.answer("⚠️ Hozir aktiv jarayon yo'q.")


# ═══════════════════════════════════════════════════════════
#  NOMA'LUM XABARLAR
# ═══════════════════════════════════════════════════════════

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(msg: Message, state: FSMContext):
    # FSM holati bo'lsa — tegishli handler ishlaydi
    if await state.get_state():
        return

    if is_admin(msg.from_user.id):
        await msg.answer("❓ Buyruq tanlanmadi.", reply_markup=kb_admin_panel())
    else:
        await msg.answer("👋 Botdan foydalanish uchun /start bosing.")
