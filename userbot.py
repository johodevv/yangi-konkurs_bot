"""
userbot.py — Pyrogram UserBot (Pyrogram 2.0.106 uchun)

Asosiy xatolar tuzatildi:
  ✅ DialogFilter → DialogFilterChatlist  (jild uchun to'g'ri type)
  ✅ GetExportedChatlistInvites → GetExportedInvites  (to'g'ri nom)
  ✅ DeleteExportedChatlistInvite → DeleteExportedInvite (to'g'ri nom)
  ✅ Mavjud link qaytarish → limit xatosidan saqlanish
"""

import asyncio
import logging

from pyrogram import Client
from pyrogram.errors import PeerIdInvalid, FloodWait, ChannelInvalid
from pyrogram.raw import functions, types as raw_types

import config
import database as db

logger = logging.getLogger(__name__)


class UserBot:
    def __init__(self):
        self.client: Client | None = None
        self._started: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> bool:
        if config.SESSION_STRING in ("", "YOUR_SESSION_STRING"):
            logger.warning("SESSION_STRING o'rnatilmagan.")
            return False
        try:
            self.client = Client(
                name="userbot_session",
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                session_string=config.SESSION_STRING,
                in_memory=True,
            )
            await self.client.start()
            me = await self.client.get_me()
            logger.info(f"UserBot ulandi: @{me.username} (id={me.id})")
            self._started = True
            return True
        except Exception as e:
            logger.error(f"UserBot ulanmadi: {e}")
            self.client = None
            self._started = False
            return False

    async def stop(self):
        if self.client and self._started:
            try:
                await self.client.stop()
                logger.info("UserBot to'xtatildi.")
            except Exception:
                pass

    @property
    def is_ready(self) -> bool:
        return bool(self.client and self._started)

    # ── Peer resolver ─────────────────────────────────────────────────────────

    async def _resolve_peer(self, channel_id: int, username: str | None = None):
        """
        Kanal uchun InputPeer oladi.
        Avval ID, muvaffaqiyatsiz bo'lsa username bilan urinadi.
        """
        # 1-urinish: channel ID bilan
        try:
            await self.client.get_chat(channel_id)
            return await self.client.resolve_peer(channel_id)
        except FloodWait as e:
            logger.warning(f"FloodWait {e.value}s")
            await asyncio.sleep(e.value + 2)
            return await self._resolve_peer(channel_id, username)
        except (PeerIdInvalid, ChannelInvalid, KeyError):
            pass
        except Exception as e:
            logger.warning(f"ID={channel_id} peer xatolik: {e}")

        # 2-urinish: username bilan
        if username:
            uname = username.lstrip("@")
            try:
                await self.client.get_chat(f"@{uname}")
                return await self.client.resolve_peer(f"@{uname}")
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
                return await self._resolve_peer(channel_id, username)
            except Exception as e:
                logger.error(f"@{uname} ham topilmadi: {e}")

        return None

    # ── Folder (DialogFilterChatlist) yaratish ────────────────────────────────

    async def _update_folder(self, peers: list) -> bool:
        """
        Telegram jildini (DialogFilterChatlist) yaratadi yoki yangilaydi.

        MUHIM: Oddiy DialogFilter emas, DialogFilterChatlist ishlatiladi!
        Faqat DialogFilterChatlist uchun ExportChatlistInvite ishlaydi.
        """
        try:
            await self.client.invoke(
                functions.messages.UpdateDialogFilter(
                    id=config.FOLDER_ID,
                    filter=raw_types.DialogFilterChatlist(
                        id=config.FOLDER_ID,
                        title=config.FOLDER_NAME,
                        pinned_peers=[],
                        include_peers=peers,
                        # has_my_invites va emoticon ixtiyoriy
                    ),
                )
            )
            logger.info(f"Folder (DialogFilterChatlist) yaratildi/yangilandi: {len(peers)} ta kanal")
            return True
        except Exception as e:
            logger.error(f"Folder yaratishda xatolik: {e}")
            return False

    # ── Mavjud invite linkni olish ────────────────────────────────────────────

    async def _get_existing_invite(self) -> str | None:
        """
        Agar folder uchun invite link allaqachon yaratilgan bo'lsa,
        uni qaytaradi. GetExportedInvites — to'g'ri funksiya nomi.
        """
        try:
            result = await self.client.invoke(
                functions.chatlists.GetExportedInvites(
                    chatlist=raw_types.InputChatlistDialogFilter(
                        filter_id=config.FOLDER_ID
                    )
                )
            )
            # result.invites — ExportedChatlistInvite obyektlar ro'yxati
            invites = getattr(result, "invites", [])
            if invites:
                url = getattr(invites[0], "url", None)
                if url:
                    logger.info(f"Mavjud link topildi: {url}")
                    return url
        except Exception as e:
            logger.debug(f"Mavjud link yo'q: {e}")
        return None

    # ── Eski linklar o'chirish ────────────────────────────────────────────────

    async def _delete_old_invites(self):
        """
        Limit (10 ta) dan oshmasligi uchun eski linklar o'chiriladi.
        DeleteExportedInvite — to'g'ri funksiya nomi.
        """
        try:
            result = await self.client.invoke(
                functions.chatlists.GetExportedInvites(
                    chatlist=raw_types.InputChatlistDialogFilter(
                        filter_id=config.FOLDER_ID
                    )
                )
            )
            invites = getattr(result, "invites", [])
            for invite in invites:
                slug = getattr(invite, "slug", None)
                if not slug:
                    # slug yo'q bo'lsa url dan olish
                    url = getattr(invite, "url", "")
                    if "addlist/" in url:
                        slug = url.split("addlist/")[-1]
                if slug:
                    await self.client.invoke(
                        functions.chatlists.DeleteExportedInvite(
                            chatlist=raw_types.InputChatlistDialogFilter(
                                filter_id=config.FOLDER_ID
                            ),
                            slug=slug,
                        )
                    )
                    logger.info(f"Eski link o'chirildi: {slug}")
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"Eski link o'chirishda xatolik: {e}")

    # ── Yangi invite link yaratish ────────────────────────────────────────────

    async def _create_invite(self, peers: list) -> str | None:
        """
        Jild uchun yangi t.me/addlist/... linki yaratadi.
        Agar limit to'lsa — eski linklar o'chiriladi va qayta uriniladi.
        """
        for attempt in range(2):
            try:
                result = await self.client.invoke(
                    functions.chatlists.ExportChatlistInvite(
                        chatlist=raw_types.InputChatlistDialogFilter(
                            filter_id=config.FOLDER_ID
                        ),
                        title=config.FOLDER_NAME,
                        peers=peers,
                    )
                )
                # result — chatlists.ExportedChatlistInvite yoki shunga o'xshash
                url = None
                if hasattr(result, "invite"):
                    url = getattr(result.invite, "url", None)
                elif hasattr(result, "url"):
                    url = result.url

                if url:
                    logger.info(f"Yangi link yaratildi: {url}")
                    return url

                logger.error(f"URL topilmadi, result: {result}")

            except Exception as e:
                err_str = str(e).lower()
                if "chatlist_invite_already" in err_str or "already" in err_str:
                    # Allaqachon bor — mavjud linkni olib qaytaramiz
                    logger.info("Link allaqachon mavjud, mavjud link olinmoqda...")
                    return await self._get_existing_invite()

                if attempt == 0:
                    logger.warning(f"Link yaratish xatolik (1-urinish): {e}")
                    logger.info("Eski linklar o'chirilmoqda...")
                    await self._delete_old_invites()
                    await asyncio.sleep(1)
                else:
                    logger.error(f"Link yaratish xatolik (2-urinish): {e}")

        return None

    # ── Asosiy ochiq funksiya ─────────────────────────────────────────────────

    async def create_folder_link(self) -> str | None:
        """
        Bazadagi barcha kanallarni Telegram jildiga qo'shadi va
        ulashish linkini qaytaradi (t.me/addlist/...).

        Qadam-baqadam:
          1. Har bir kanal uchun InputPeer olish
          2. DialogFilterChatlist yaratish/yangilash
          3. Mavjud link bormi tekshirish
          4. Yangi link yaratish
        """
        if not self.is_ready:
            logger.error("UserBot tayyor emas.")
            return None

        channels = db.get_channels()
        if not channels:
            logger.warning("Bazada kanallar yo'q.")
            return None

        # 1. InputPeer lar yig'ish
        peers = []
        for ch_id, ch_user, ch_title, _ in channels:
            peer = await self._resolve_peer(ch_id, ch_user)
            if peer:
                peers.append(peer)
                logger.debug(f"  ✅ Peer: {ch_title}")
            else:
                logger.warning(f"  ❌ Peer topilmadi: {ch_title} ({ch_id})")
            await asyncio.sleep(0.4)

        if not peers:
            logger.error("Hech bir peer topilmadi.")
            return None

        logger.info(f"Jami {len(peers)}/{len(channels)} peer topildi.")

        # 2. Folder yaratish/yangilash
        if not await self._update_folder(peers):
            return None

        await asyncio.sleep(1)

        # 3. Mavjud link bormi?
        existing = await self._get_existing_invite()
        if existing:
            return existing

        # 4. Yangi link yaratish
        return await self._create_invite(peers)
