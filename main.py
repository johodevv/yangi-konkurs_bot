"""
main.py — Render.com uchun moslashtirilgan ishga tushiruvchi fayl.

Nima qiladi:
  1. SQLite bazasini ishga tushiradi
  2. UserBot (Pyrogram) ni ulaydi
  3. aiohttp orqali $PORT ni band qiladi (Render port scan xatosini oldini oladi)
  4. Aiogram polling ni ishga tushiradi
  5. Hammasi asyncio.gather orqali parallel ishlaydi
"""

import asyncio
import logging
import sys

from aiohttp import web

import config
import database as db
from bot import bot, dp
from userbot import UserBot

# ── Logging sozlamalari ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── aiohttp web-server (Render port binding) ──────────────────────────────────

async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint — Render va UptimeRobot uchun."""
    channel_count = db.get_channel_count()
    user_count = db.get_user_count()
    return web.Response(
        text=(
            f"✅ Bot ishlayapti!\n"
            f"Kanallar: {channel_count}\n"
            f"Foydalanuvchilar: {user_count}"
        ),
        content_type="text/plain",
    )


async def run_web_server():
    """aiohttp serverni $PORT da ishga tushiradi."""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
    await site.start()

    logger.info(f"Web server ishga tushdi: http://0.0.0.0:{config.PORT}")

    # Server to'xtatilguncha kutish
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


# ── Polling ───────────────────────────────────────────────────────────────────

async def run_bot():
    """Aiogram botni polling rejimida ishga tushiradi."""
    logger.info("Bot polling ishga tushmoqda…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Bot polling to'xtatildi.")


# ── Asosiy funksiya ───────────────────────────────────────────────────────────

async def main():
    # 1. Bazani ishga tushirish
    db.init_db()
    logger.info("Ma'lumotlar bazasi tayyor.")

    # 2. UserBot ni ulash
    ub = UserBot()
    started = await ub.start()

    # UserBot referensini bot.py ga uzatish
    import bot as bot_module
    bot_module.userbot = ub

    if not started:
        logger.warning(
            "UserBot ishga tushmadi — faqat bot ishlaydi. "
            "SESSION_STRING to'g'ri o'rnatilganligini tekshiring."
        )

    # 3. Web server va bot polling ni parallel ishga tushirish
    logger.info("Barcha servislar ishga tushmoqda…")
    try:
        await asyncio.gather(
            run_web_server(),
            run_bot(),
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("To'xtatish signali olindi.")
    finally:
        await ub.stop()
        logger.info("Dastur to'xtatildi.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Chiqildi.")
