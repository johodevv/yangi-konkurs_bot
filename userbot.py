import asyncio
import logging

from pyrogram import Client
from pyrogram.errors import PeerIdInvalid, FloodWait, ChannelInvalid
from pyrogram.raw import functions, types as raw_types

import config
import database as db

logger = logging.getLogger(__name__)


class UserBot:
    """Pyrogram asosidagi userbot — folder yaratish va link olish."""

    def __init__(self):
        self.client: Client | None = None
        self._started = False

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> bool:
        if not config.SESSION_STRING or config.SESSION_STRING == "YOUR_SESSION_STRING_HERE":
            logger.warning("SESSION_STRING o'rnatilmagan — UserBot ishga tushmadi.")
            return False
        try:
            self.client = Client(
                name="userbot",
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                session_string=config.SESSION_STRING,
                in_memory=True,
            )
            await self.client.start()
            me = await self.client.get_me()
            logger.info(f"UserBot ulandi: @{me.username} ({me.id})")
            self._started = True
            return True
        except Exception as e:
            logger.error(f"UserBot ulanishda xatolik: {e}")
            self.client = None
            return False

    async def stop(self):
        if self.client and self._started:
            try:
                await self.client.stop()
                logger.info("UserBot to'xtatildi.")
            except Exception as e:
                logger.error(f"UserBot to'xtatishda xatolik: {e}")

    @property
    def is_ready(self) -> bool:
        return self.client is not None and self._started

    # ── Peer resolution (PeerIdInvalid xatosini oldini oladi) ──────────────

    async def _resolve_peer_safe(self, channel_id: int, channel_username: str | None):
        """
        Avval ID bilan keshga yuklashga harakat qiladi.
        Agar PeerIdInvalid bo'lsa — username orqali yuklaydi.
        """
        try:
            await self.client.get_chat(channel_id)
            return await self.client.resolve_peer(channel_id)
        except (PeerIdInvalid, ChannelInvalid):
            logger.warning(
                f"Kanal {channel_id} ID bilan topilmadi, "
                f"username bilan urinilmoqda: @{channel_username}"
            )
            if channel_username:
                try:
                    username = channel_username.lstrip("@")
                    await self.client.get_chat(f"@{username}")
                    return await self.client.resolve_peer(f"@{username}")
                except Exception as e:
                    logger.error(f"Username bilan ham topilmadi ({channel_username}): {e}")
        except FloodWait as e:
            logger.warning(f"FloodWait: {e.value}s kutilmoqda…")
            await asyncio.sleep(e.value + 1)
            return await self._resolve_peer_safe(channel_id, channel_username)
        except Exception as e:
            logger.error(f"Peer {channel_id} uchun xatolik: {e}")
        return None

    # ── Folder yaratish va link olish ──────────────────────────────────────

    async def create_folder_link(self) -> str | None:
        """
        Bazadagi barcha kanallarni bitta Telegram jildiga (DialogFilter)
        qo'shadi va ExportChatlistInvite orqali ulashish linkini qaytaradi.
        """
        if not self.is_ready:
            logger.error("UserBot tayyor emas!")
            return None

        channels = db.get_channels()
        if not channels:
            logger.warning("Bazada kanallar yo'q.")
            return None

        # Har bir kanal uchun Peer olish
        input_peers = []
        for channel_id, ch_username, ch_title, _ in channels:
            peer = await self._resolve_peer_safe(channel_id, ch_username)
            if peer is not None:
                input_peers.append(peer)
            await asyncio.sleep(0.3)  # rate-limit

        if not input_peers:
            logger.error("Hech bir kanal uchun peer topilmadi.")
            return None

        try:
            # 1. Folder (DialogFilter) yaratish / yangilash
            dialog_filter = raw_types.DialogFilter(
                id=config.FOLDER_ID,
                title=config.FOLDER_NAME,
                pinned_peers=[],
                include_peers=input_peers,
                exclude_peers=[],
            )
            await self.client.invoke(
                functions.messages.UpdateDialogFilter(
                    id=config.FOLDER_ID,
                    filter=dialog_filter,
                )
            )
            logger.info(f"Folder yaratildi/yangilandi (ID: {config.FOLDER_ID})")

            # 2. Folder invite-link olish
            result = await self.client.invoke(
                functions.chatlists.ExportChatlistInvite(
                    chatlist=raw_types.InputChatlistDialogFilter(
                        filter_id=config.FOLDER_ID
                    ),
                    title=config.FOLDER_NAME,
                    peers=input_peers,
                )
            )

            if result and hasattr(result, "invite") and hasattr(result.invite, "url"):
                url = result.invite.url
                logger.info(f"Folder link olindi: {url}")
                return url

            logger.error(f"Kutilmagan javob: {result}")
            return None

        except Exception as e:
            logger.error(f"Folder link yaratishda xatolik: {e}")
            return None
