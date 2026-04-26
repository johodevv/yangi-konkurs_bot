import asyncio
import logging
import sys

from aiohttp import web, ClientSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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


async def handle_root(r): return web.Response(text=f"Bot ishlayapti | Kanallar: {db.get_channel_count()}")
async def handle_ping(r): return web.Response(text="pong")


async def run_web():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/health", handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logger.info(f"Web server: http://0.0.0.0:{config.PORT}")
    await asyncio.Event().wait()


async def self_ping():
    import os
    url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not url:
        return
    ping = f"{url.rstrip('/')}/ping"
    logger.info(f"Self-ping: {ping}")
    await asyncio.sleep(30)
    while True:
        try:
            async with ClientSession() as s:
                async with s.get(ping, timeout=10) as r:
                    logger.debug(f"Self-ping: {r.status}")
        except Exception as e:
            logger.warning(f"Self-ping xatolik: {e}")
        await asyncio.sleep(240)


async def run_bot():
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def main():
    db.init_db()

    ub = UserBot()
    ok = await ub.start()

    import bot as bot_module
    bot_module.userbot = ub

    # APScheduler
    sched = AsyncIOScheduler()
    sched.start()
    bot_module.scheduler = sched

    # Bazadagi pending contestlarni qayta yuklash
    for cid, ctext, run_at_str in db.get_pending_contests():
        from datetime import datetime
        from bot import run_scheduled_contest
        try:
            run_at = datetime.strptime(run_at_str, "%Y-%m-%d %H:%M:%S")
            if run_at > datetime.now():
                sched.add_job(
                    run_scheduled_contest, "date",
                    run_date=run_at,
                    args=[cid, ctext],
                    id=f"contest_{cid}",
                    misfire_grace_time=300,
                )
                logger.info(f"Pending contest qayta yuklandi: id={cid}")
        except Exception as e:
            logger.warning(f"Contest {cid} yuklanmadi: {e}")

    if not ok:
        logger.warning("UserBot ishlamadi.")

    try:
        await asyncio.gather(run_web(), run_bot(), self_ping())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        sched.shutdown(wait=False)
        await ub.stop()


if __name__ == "__main__":
    asyncio.run(main())
