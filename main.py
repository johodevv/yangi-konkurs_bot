"""
main.py — Render.com bepul tier uchun 24/7 ishlaydigan versiya

Render 24/7 yechimi:
  - aiohttp server $PORT ni band qiladi (port scan timeout xatosi yo'q)
  - /ping endpoint UptimeRobot tomonidan har 5 daqiqada chaqiriladi
  - Bu Render servisni "uxlatib qo'ymaslik" imkonini beradi
"""

import asyncio
import logging
import sys

from aiohttp import web, ClientSession

import config
import database as db
from bot import bot, dp
from userbot import UserBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Health check endpointlar ──────────────────────────────────────────────────

async def handle_root(request: web.Request) -> web.Response:
    return web.Response(
        text=(
            f"✅ Bot ishlayapti!\n"
            f"Kanallar: {db.get_channel_count()}\n"
            f"Foydalanuvchilar: {db.get_user_count()}"
        )
    )

async def handle_ping(request: web.Request) -> web.Response:
    """UptimeRobot shu endpointni ping qiladi."""
    return web.Response(text="pong")


# ── Web server ────────────────────────────────────────────────────────────────

async def run_web_server():
    app = web.Application()
    app.router.add_get("/",      handle_root)
    app.router.add_get("/ping",  handle_ping)
    app.router.add_get("/health", handle_root)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
    await site.start()
    logger.info(f"Web server: http://0.0.0.0:{config.PORT}")

    # Server to'xtatilguncha ishlayveradi
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


# ── Self-ping (Render uxlamasligi uchun) ──────────────────────────────────────

async def keep_alive_ping():
    """
    Render servisni o'zi o'zini har 4 daqiqada ping qiladi.
    Bu UptimeRobot bo'lmasa ham ishlaydi.
    Render URL ni RENDER_EXTERNAL_URL env var orqali oladi.
    """
    import os
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")

    if not render_url:
        logger.info("RENDER_EXTERNAL_URL topilmadi — self-ping o'chirilgan.")
        return

    ping_url = f"{render_url.rstrip('/')}/ping"
    logger.info(f"Self-ping yoqildi: {ping_url} (har 4 daqiqada)")

    await asyncio.sleep(30)  # Server to'liq ishga tushguncha kutish

    while True:
        try:
            async with ClientSession() as session:
                async with session.get(ping_url, timeout=10) as resp:
                    if resp.status == 200:
                        logger.debug("Self-ping OK")
                    else:
                        logger.warning(f"Self-ping status: {resp.status}")
        except Exception as e:
            logger.warning(f"Self-ping xatolik: {e}")

        await asyncio.sleep(240)  # 4 daqiqa


# ── Bot polling ───────────────────────────────────────────────────────────────

async def run_bot():
    logger.info("Bot polling ishga tushdi...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        logger.info("Bot polling to'xtatildi.")


# ── Asosiy funksiya ───────────────────────────────────────────────────────────

async def main():
    # 1. Bazani ishga tushirish
    db.init_db()
    logger.info("Database tayyor.")

    # 2. UserBot ni ulash
    ub = UserBot()
    ok = await ub.start()

    # UserBot ni bot.py ga uzatish
    import bot as bot_module
    bot_module.userbot = ub

    if not ok:
        logger.warning(
            "UserBot ishlamadi. SESSION_STRING to'g'ri o'rnatilganligini tekshiring.\n"
            "UserBotsiz: kanal qo'shish ishlaydi, lekin jild linki olinmaydi."
        )

    # 3. Hamma narsani parallel ishga tushirish
    logger.info("Barcha servislar ishga tushmoqda...")
    try:
        await asyncio.gather(
            run_web_server(),
            run_bot(),
            keep_alive_ping(),
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("To'xtatish signali.")
    finally:
        await ub.stop()
        logger.info("Dastur to'xtatildi.")


if __name__ == "__main__":
    asyncio.run(main())
