"""
bot.py — Konkurs Jild Boti

Tuzatilganlar:
  ✅ Obuna tekshiruv KICKED status bilan to'g'ri
  ✅ 2 ta jild (kichik/yirik kanallar)
  ✅ Rejalashtirilgan konkurs (APScheduler)
  ✅ DefaultBotProperties (aiogram 3.7+)
"""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
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
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database as db

logger  = logging.getLogger(__name__)
bot     = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp      = Dispatcher(storage=storage)
router  = Router()
dp.include_router(router)

userbot    = None   # main.py tomonidan o'rnatiladi
scheduler  = None   # main.py tomonidan o'rnatiladi


# ═══════════════════════════════════════════════════════════
#  FSM
# ═══════════════════════════════════════════════════════════

class UserFlow(StatesGroup):
    waiting_channel_link = State()
    waiting_admin_check  = State()

class AdminFlow(StatesGroup):
    waiting_broadcast        = State()
    waiting_schedule_message = State()
    waiting_schedule_time    = State()


# ═══════════════════════════════════════════════════════════
#  KLAVIATURALAR
# ═══════════════════════════════════════════════════════════

def kb_subscribe() -> InlineKeyboardMarkup:
    bld = InlineKeyboardBuilder()
    for ch in config.REQUIRED:
        emoji = "📢" if ch["type"] == "kanal" else "👥"
        bld.button(text=f"{emoji} {ch['title']}", url=ch["url"])
        bld.adjust(1)
    bld.button(text="✅ Obuna bo'ldim — Tekshir", callback_data="check_sub")
    bld.adjust(1)
    return bld.as_markup()


def kb_admin_grant(bot_username: str) -> InlineKeyboardMarkup:
    bld = InlineKeyboardBuilder()
    bld.button(
        text="📖 Qo'llanma — Admin berish",
        url=f"https://t.me/{bot_username}"
    )
    bld.button(
        text="✅ Admin berdim, kanalimni qo'sh!",
        callback_data="admin_given"
    )
    bld.adjust(1)
    return bld.as_markup()


def kb_folder(small_link: str | None, big_link: str | None) -> InlineKeyboardMarkup:
    bld = InlineKeyboardBuilder()
    if small_link:
        bld.button(text="📁 Kichik kanallar jildi", url=small_link)
    if big_link:
        bld.button(text="📁 Yirik kanallar jildi", url=big_link)
    bld.adjust(1)
    return bld.as_markup()


def kb_folder_single(link: str, label: str = "📁 Jildga qo'shilish") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, url=link)
    ]])


def kb_admin_panel() -> InlineKeyboardMarkup:
    bld = InlineKeyboardBuilder()
    bld.button(text="🚀 Konkursni hozir boshlash",   callback_data="admin_broadcast")
    bld.button(text="⏰ Konkursni rejalashtirish",   callback_data="admin_schedule")
    bld.button(text="📋 Rejalashtirilganlar",         callback_data="admin_scheduled_list")
    bld.button(text="📊 Statistika",                  callback_data="admin_stats")
    bld.button(text="📋 Kanallar ro'yxati",           callback_data="admin_channels")
    bld.button(text="🔗 Jild linkini yangilash",      callback_data="admin_folder")
    bld.adjust(1)
    return bld.as_markup()


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_back")
    ]])


# ═══════════════════════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid == config.ADMIN_ID


def is_cancel(text: str | None) -> bool:
    if not text:
        return False
    return text.strip().split("@")[0].lower() == "/cancel"


async def get_not_subscribed(user_id: int) -> list:
    """
    Obuna bo'lmagan kanallar ro'yxatini qaytaradi.
    ChatMemberStatus.KICKED va LEFT — obuna emas.
    """
    result = []
    for ch in config.REQUIRED:
        try:
            m = await bot.get_chat_member(f"@{ch['username']}", user_id)
            # MEMBER, ADMINISTRATOR, CREATOR — obuna
            # LEFT, KICKED, RESTRICTED — obuna emas
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                result.append(ch)
        except TelegramBadRequest as e:
            # "user not found" yoki kanal topilmadi
            logger.warning(f"Obuna tekshirish ({ch['username']}): {e}")
        except TelegramForbiddenError:
            # Bot kanalda admin emas — skip (obuna deb hisoblaymiz)
            logger.warning(f"Bot @{ch['username']} kanalda admin emas!")
        except Exception as e:
            logger.error(f"Obuna tekshirish xatolik ({ch['username']}): {e}")
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
        logger.error(f"Invite link ({channel_id}): {e}")
        return None


async def do_broadcast(message_text: str, small_link: str | None, big_link: str | None):
    """
    Barcha kanallarga xabar yuboradi.
    Tugma: agar ikkala jild bo'lsa ikkita, bitta bo'lsa bitta.
    """
    keyboard = None
    if small_link or big_link:
        keyboard = kb_folder(small_link, big_link)

    channels = db.get_channels()
    ok = fail = 0

    for ch_id, _, ch_title, _ in channels:
        try:
            await bot.send_message(
                chat_id=ch_id,
                text=message_text,
                reply_markup=keyboard,
            )
            ok += 1
        except TelegramForbiddenError:
            logger.warning(f"Bot kanaldan chiqarilgan: {ch_title}")
            db.remove_channel(ch_id)
            fail += 1
        except TelegramBadRequest as e:
            logger.warning(f"BadRequest ({ch_title}): {e}")
            fail += 1
        except Exception as e:
            logger.error(f"Yuborish xatolik ({ch_title}): {e}")
            fail += 1
        await asyncio.sleep(0.3)

    logger.info(f"Broadcast tugadi: ok={ok}, fail={fail}")
    return ok, fail


# ═══════════════════════════════════════════════════════════
#  REJALASHTIRILGAN KONKURS ISHGA TUSHIRUVCHI
# ═══════════════════════════════════════════════════════════

async def run_scheduled_contest(contest_id: int, message_text: str):
    """APScheduler tomonidan chaqiriladi."""
    logger.info(f"Rejalashtirilgan konkurs ishga tushdi: id={contest_id}")

    # Jild linklari
    small_link = big_link = None
    if userbot and userbot.is_ready:
        links = await userbot.create_folder_links()
        small_link = links.get("small")
        big_link   = links.get("big")

    ok, fail = await do_broadcast(message_text, small_link, big_link)
    db.mark_contest_done(contest_id)

    # Adminga natija
    try:
        await bot.send_message(
            config.ADMIN_ID,
            f"✅ <b>Rejalashtirilgan konkurs yakunlandi!</b>\n\n"
            f"✔️ Yuborildi: <b>{ok} ta</b>\n"
            f"❌ Xatolik: <b>{fail} ta</b>"
        )
    except Exception:
        pass


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
            f"👋 <b>Salom, Admin!</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
            f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>",
            reply_markup=kb_admin_panel()
        )
        return

    # ── Obuna tekshirish ──
    not_sub = await get_not_subscribed(msg.from_user.id)
    if not_sub:
        names = "\n".join(
            f"{'📢' if ch['type']=='kanal' else '👥'} <b>{ch['title']}</b>"
            for ch in not_sub
        )
        await msg.answer(
            "👋 <b>Botga xush kelibsiz!</b>\n\n"
            "⚠️ <b>Avval quyidagilarga obuna bo'ling:</b>\n\n"
            f"{names}\n\n"
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
            f"❌ Hali {names}ga obuna bo'lmagansiz!\n"
            "Obuna bo'lib, qayta bosing.",
            show_alert=True
        )
        return

    await call.answer("✅ Tasdiqlandi!", show_alert=False)
    try:
        await call.message.delete()
    except Exception:
        pass
    await _ask_channel_link(call.message, state, call.from_user.id)


# ═══════════════════════════════════════════════════════════
#  KANAL LINKI SO'RASH
# ═══════════════════════════════════════════════════════════

async def _ask_channel_link(msg: Message, state: FSMContext, user_id: int):
    await state.set_state(UserFlow.waiting_channel_link)
    await state.update_data(user_id=user_id)
    await msg.answer(
        "🎉 <b>Obuna tasdiqlandi!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📢 <b>Kanalingiz username yoki linkini yuboring</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Misol:</b>\n"
        "• <code>@mening_kanalim</code>\n"
        "• <code>https://t.me/mening_kanalim</code>\n\n"
        "❌ Bekor: /cancel"
    )


# ═══════════════════════════════════════════════════════════
#  KANAL LINKI QABUL QILISH
# ═══════════════════════════════════════════════════════════

@router.message(UserFlow.waiting_channel_link)
async def process_channel_link(msg: Message, state: FSMContext):
    if not msg.text:
        await msg.answer("⚠️ Kanal username yoki link yuboring.")
        return

    text = msg.text.strip()

    if text.startswith("/"):
        if is_cancel(text):
            await state.clear()
            await msg.answer("❌ Bekor qilindi. /start")
        else:
            await msg.answer("⚠️ Avval kanal linkini yuboring yoki /cancel.")
        return

    # t.me/xxx → @xxx
    if "t.me/" in text and "+=" not in text:
        text = "@" + text.split("t.me/")[-1].strip("/").split("?")[0]

    try:
        chat = await bot.get_chat(text)
    except (TelegramBadRequest, TelegramForbiddenError):
        await msg.answer(
            "❌ <b>Kanal topilmadi!</b>\n\n"
            "• Username to'g'ri yozilganmi?\n"
            "• Kanal public ekanmi?\n\n"
            "Qaytadan yuboring yoki /cancel:"
        )
        return
    except Exception as e:
        logger.error(f"get_chat: {e}")
        await msg.answer("⚠️ Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        return

    if db.channel_exists(chat.id):
        await msg.answer(
            f"⚠️ <b>{chat.title}</b> allaqachon jildda mavjud!\n\n"
            "Boshqa kanal linki yuboring yoki /cancel."
        )
        return

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
        "━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Botga admin bering</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Qadamlar:</b>\n"
        "1️⃣ Kanalingizga kiring\n"
        "2️⃣ Sozlamalar → Adminlar → Admin qo'shish\n"
        f"3️⃣ <code>@{me.username}</code> qidiring\n"
        "4️⃣ Admin qilib qo'shing\n"
        "5️⃣ Pastdagi ✅ tugmani bosing 👇",
        reply_markup=kb_admin_grant(me.username)
    )


# ═══════════════════════════════════════════════════════════
#  ADMIN BERILDI
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_given")
async def cb_admin_given(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    channel_id    = data.get("channel_id")
    channel_title = data.get("channel_title", "Noma'lum")
    channel_user  = data.get("channel_username", "")

    if not channel_id:
        await call.answer("⚠️ Seans tugagan. /start bosing.", show_alert=True)
        await state.clear()
        return

    if not await check_bot_admin(channel_id):
        await call.answer(
            "❌ Bot hali admin emas!\n"
            "Admin qilib, qayta bosing.",
            show_alert=True
        )
        return

    await call.answer("⏳ Qo'shilmoqda...", show_alert=False)

    invite_link = await get_invite_link(channel_id)
    uid = data.get("user_id") or call.from_user.id
    success = db.add_channel(channel_id, channel_user, channel_title, invite_link, uid)

    if not success:
        await call.message.edit_text(
            "❌ <b>Bazaga saqlashda xatolik.</b>\n/start"
        )
        await state.clear()
        return

    await state.clear()

    # Jild linklari
    small_link = big_link = None
    if userbot and userbot.is_ready:
        wait = await call.message.answer("⏳ Jild yangilanmoqda...")
        try:
            links = await userbot.create_folder_links()
            small_link = links.get("small")
            big_link   = links.get("big")
        except Exception as e:
            logger.error(f"create_folder_links: {e}")
        try:
            await wait.delete()
        except Exception:
            pass

    text = (
        f"🎊 <b>Tabriklaymiz!</b>\n\n"
        f"✅ <b>{channel_title}</b> jildga qo'shildi!\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📁 Jildga qo'shilish uchun tugmani bosing 👇"
    )

    if small_link or big_link:
        await call.message.edit_text(
            text, reply_markup=kb_folder(small_link, big_link)
        )
    else:
        await call.message.edit_text(
            f"✅ <b>{channel_title}</b> bazaga qo'shildi!\n\n"
            "📁 Jild linki broz orada tayyorlanadi."
        )

    try:
        await bot.send_message(
            config.ADMIN_ID,
            f"🆕 <b>Yangi kanal!</b>\n\n"
            f"📌 {channel_title}\n"
            f"👤 {channel_user or 'private'}\n"
            f"👤 Egasi: {('@' + call.from_user.username) if call.from_user.username else call.from_user.id}\n"
            f"📊 Jami: {db.get_channel_count()} ta"
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  ADMIN PANEL
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


@router.callback_query(F.data == "admin_back")
async def cb_admin_back(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer(); return
    await state.clear()
    await call.answer()
    await call.message.edit_text(
        f"🛠 <b>Admin Panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
        f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>",
        reply_markup=kb_admin_panel()
    )


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer(); return
    await call.answer()
    await call.message.edit_text(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{db.get_user_count()} ta</b>\n"
        f"📢 Kanallar: <b>{db.get_channel_count()} ta</b>",
        reply_markup=kb_back()
    )


@router.callback_query(F.data == "admin_channels")
async def cb_admin_channels(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer(); return
    await call.answer()
    channels = db.get_channels()
    if not channels:
        await call.message.edit_text("📋 Kanallar yo'q.", reply_markup=kb_back())
        return
    lines = [f"📋 <b>Kanallar ({len(channels)} ta):</b>\n"]
    for i, (ch_id, ch_user, ch_title, _) in enumerate(channels, 1):
        lines.append(f"{i}. <b>{ch_title}</b> — {ch_user or 'private'}")
    await call.message.edit_text("\n".join(lines), reply_markup=kb_back())


@router.callback_query(F.data == "admin_folder")
async def cb_admin_folder(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer(); return

    if not userbot or not userbot.is_ready:
        await call.answer("❌ UserBot ishlamayapti!", show_alert=True)
        return

    await call.answer("⏳ Jild yangilanmoqda...", show_alert=False)

    try:
        links = await userbot.create_folder_links()
        small_link = links.get("small")
        big_link   = links.get("big")
        sc = links.get("small_count", 0)
        bc = links.get("big_count", 0)
    except Exception as e:
        logger.error(f"create_folder_links: {e}")
        await call.message.answer("❌ Jild linki olinmadi.")
        return

    if not small_link and not big_link:
        await call.message.answer("❌ Jild linki olinmadi. Kanallar borligini tekshiring.")
        return

    text = (
        f"✅ <b>Jildlar yangilandi!</b>\n\n"
        f"📁 Kichik kanallar: <b>{sc} ta</b>\n"
        f"📁 Yirik kanallar: <b>{bc} ta</b>"
    )
    await call.message.answer(text, reply_markup=kb_folder(small_link, big_link))


# ═══════════════════════════════════════════════════════════
#  HOZIRGI KONKURS (broadcast)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer(); return
    if db.get_channel_count() == 0:
        await call.answer("❌ Bazada kanallar yo'q!", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminFlow.waiting_broadcast)
    await call.message.edit_text(
        "🚀 <b>Konkurs xabarini yuboring</b>\n\n"
        "Xabar barcha kanallarga \"Jildga qo'shilish\" tugmasi bilan yuboriladi.\n\n"
        "❌ Bekor: /cancel",
        reply_markup=None
    )


@router.message(AdminFlow.waiting_broadcast)
async def process_broadcast(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    if msg.text and is_cancel(msg.text):
        await state.clear()
        await msg.answer("❌ Bekor.", reply_markup=kb_admin_panel())
        return
    if msg.text and msg.text.startswith("/"):
        await msg.answer("⚠️ Xabar yuboring yoki /cancel.")
        return

    await state.clear()

    small_link = big_link = None
    if userbot and userbot.is_ready:
        wait = await msg.answer("⏳ Jild linklari olinmoqda...")
        try:
            links = await userbot.create_folder_links()
            small_link = links.get("small")
            big_link   = links.get("big")
        except Exception as e:
            logger.error(f"create_folder_links: {e}")
        try:
            await wait.delete()
        except Exception:
            pass

    keyboard = kb_folder(small_link, big_link) if (small_link or big_link) else None
    channels = db.get_channels()
    ok = fail = 0
    prog = await msg.answer(f"📤 Yuborilmoqda: 0/{len(channels)}")

    for i, (ch_id, _, ch_title, _) in enumerate(channels, 1):
        try:
            await bot.copy_message(
                chat_id=ch_id,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id,
                reply_markup=keyboard,
            )
            ok += 1
        except TelegramForbiddenError:
            db.remove_channel(ch_id)
            fail += 1
        except Exception as e:
            logger.warning(f"({ch_title}): {e}")
            fail += 1
        if i % 5 == 0:
            try:
                await prog.edit_text(f"📤 Yuborilmoqda: {i}/{len(channels)}")
            except Exception:
                pass
        await asyncio.sleep(0.3)

    try:
        await prog.delete()
    except Exception:
        pass

    status = (
        f"✅ <b>Konkurs boshlandi!</b>\n\n"
        f"✔️ Yuborildi: <b>{ok} ta</b>\n"
        f"❌ Xatolik: <b>{fail} ta</b>"
    )
    if not small_link and not big_link:
        status += "\n\n⚠️ Jild linki olinmadi — tugmasiz yuborildi."
    await msg.answer(status, reply_markup=kb_admin_panel())


# ═══════════════════════════════════════════════════════════
#  REJALASHTIRILGAN KONKURS
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_schedule")
async def cb_admin_schedule(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer(); return
    if db.get_channel_count() == 0:
        await call.answer("❌ Bazada kanallar yo'q!", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminFlow.waiting_schedule_message)
    await call.message.edit_text(
        "⏰ <b>Rejalashtirilgan konkurs</b>\n\n"
        "<b>1-qadam:</b> Konkurs xabarini yuboring.\n\n"
        "❌ Bekor: /cancel",
        reply_markup=None
    )


@router.message(AdminFlow.waiting_schedule_message)
async def process_schedule_message(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    if msg.text and is_cancel(msg.text):
        await state.clear()
        await msg.answer("❌ Bekor.", reply_markup=kb_admin_panel())
        return
    if msg.text and msg.text.startswith("/"):
        await msg.answer("⚠️ Xabar yuboring yoki /cancel.")
        return

    await state.update_data(schedule_text=msg.text or "")
    await state.set_state(AdminFlow.waiting_schedule_time)

    now = datetime.now()
    await msg.answer(
        "✅ Xabar qabul qilindi!\n\n"
        "<b>2-qadam:</b> Konkurs vaqtini kiriting.\n\n"
        "📅 <b>Format:</b> <code>DD.MM.YYYY HH:MM</code>\n\n"
        f"📌 <b>Misol:</b>\n"
        f"<code>{(now + timedelta(hours=1)).strftime('%d.%m.%Y %H:%M')}</code>\n\n"
        "❌ Bekor: /cancel"
    )


@router.message(AdminFlow.waiting_schedule_time)
async def process_schedule_time(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    if msg.text and is_cancel(msg.text):
        await state.clear()
        await msg.answer("❌ Bekor.", reply_markup=kb_admin_panel())
        return

    text = (msg.text or "").strip()
    try:
        run_at = datetime.strptime(text, "%d.%m.%Y %H:%M")
    except ValueError:
        await msg.answer(
            "❌ <b>Format xato!</b>\n\n"
            "To'g'ri format: <code>DD.MM.YYYY HH:MM</code>\n"
            f"Misol: <code>{(datetime.now() + timedelta(hours=1)).strftime('%d.%m.%Y %H:%M')}</code>\n\n"
            "Qaytadan yuboring:"
        )
        return

    if run_at <= datetime.now():
        await msg.answer(
            "❌ <b>Vaqt o'tib ketgan!</b>\n\n"
            "Kelajak vaqtini kiriting.\n"
            "Qaytadan yuboring:"
        )
        return

    data = await state.get_data()
    schedule_text = data.get("schedule_text", "")
    await state.clear()

    contest_id = db.add_contest(schedule_text, run_at.strftime("%Y-%m-%d %H:%M:%S"))

    # APScheduler ga qo'shish
    if scheduler:
        scheduler.add_job(
            run_scheduled_contest,
            "date",
            run_date=run_at,
            args=[contest_id, schedule_text],
            id=f"contest_{contest_id}",
            misfire_grace_time=300,
        )
        logger.info(f"Konkurs rejalashtirildi: id={contest_id}, vaqt={run_at}")

    await msg.answer(
        f"✅ <b>Konkurs rejalashtirildi!</b>\n\n"
        f"📅 Vaqt: <b>{run_at.strftime('%d.%m.%Y %H:%M')}</b>\n"
        f"🆔 ID: <code>{contest_id}</code>\n\n"
        "Bot o'sha vaqtda avtomatik konkursni boshlaydi.",
        reply_markup=kb_admin_panel()
    )


@router.callback_query(F.data == "admin_scheduled_list")
async def cb_scheduled_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer(); return
    await call.answer()

    contests = db.get_pending_contests()
    if not contests:
        await call.message.edit_text(
            "📋 Rejalashtirilgan konkurslar yo'q.",
            reply_markup=kb_back()
        )
        return

    lines = ["📋 <b>Kutilayotgan konkurslar:</b>\n"]
    for cid, ctext, run_at in contests:
        preview = (ctext[:40] + "...") if len(ctext) > 40 else ctext
        lines.append(f"🆔 {cid} | 📅 {run_at}\n📝 {preview}\n")

    bld = InlineKeyboardBuilder()
    for cid, _, _ in contests:
        bld.button(text=f"❌ #{cid} ni bekor qilish", callback_data=f"cancel_contest_{cid}")
    bld.button(text="🔙 Orqaga", callback_data="admin_back")
    bld.adjust(1)

    await call.message.edit_text("\n".join(lines), reply_markup=bld.as_markup())


@router.callback_query(F.data.startswith("cancel_contest_"))
async def cb_cancel_contest(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer(); return

    contest_id = int(call.data.split("_")[-1])
    db.cancel_contest(contest_id)

    if scheduler:
        try:
            scheduler.remove_job(f"contest_{contest_id}")
        except Exception:
            pass

    await call.answer(f"✅ Konkurs #{contest_id} bekor qilindi.", show_alert=True)
    await cb_scheduled_list(call)


# ═══════════════════════════════════════════════════════════
#  /cancel
# ═══════════════════════════════════════════════════════════

@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await msg.answer("❌ Bekor qilindi. /start")
    else:
        await msg.answer("⚠️ Hozir aktiv jarayon yo'q.")


# ═══════════════════════════════════════════════════════════
#  NOMA'LUM
# ═══════════════════════════════════════════════════════════

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(msg: Message, state: FSMContext):
    if await state.get_state():
        return
    if is_admin(msg.from_user.id):
        await msg.answer("❓ Buyruq tanlanmadi.", reply_markup=kb_admin_panel())
    else:
        await msg.answer("👋 Botdan foydalanish uchun /start bosing.")
