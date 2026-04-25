import asyncio
import logging
from pyrogram import Client
from pyrogram.errors import PeerIdInvalid, FloodWait, ChannelInvalid, ChannelPrivate
from pyrogram.raw import functions, types as raw_types
import config
import database as db

logger = logging.getLogger(__name__)

class UserBot:
    def __init__(self):
        self.client: Client | None = None
        self._started = False

    async def start(self) -> bool:
        if not config.SESSION_STRING or config.SESSION_STRING == "YOUR_SESSION_STRING_HERE":
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
            self._started = True
            return True
        except Exception as e:
            logger.error(f"UserBot ulanishda xatolik: {e}")
            return False

    async def create_folder_link(self):
        if not self.client or not self._started:
            return None, "UserBot ulanmagan."

        channels = db.get_all_channels()
        if not channels:
            return None, "Bazada kanallar yo'q."

        input_peers = []
        for ch in channels:
            try:
                # UserBot avval kanalga a'zo ekanini tekshiradi
                peer = await self.client.resolve_peer(ch['channel_id'])
                input_peers.append(peer)
            except (PeerIdInvalid, ChannelInvalid, ChannelPrivate):
                try:
                    # Agar a'zo bo'lmasa, qo'shilishga harakat qiladi
                    await self.client.join_chat(ch['channel_id'])
                    peer = await self.client.resolve_peer(ch['channel_id'])
                    input_peers.append(peer)
                except Exception as e:
                    logger.warning(f"Kanalga ({ch['channel_id']}) qo'shilib bo'lmadi: {e}")

        if not input_peers:
            return None, "Hech bir kanalga kirib bo'lmadi."

        try:
            # Folder yaratish
            await self.client.invoke(
                functions.messages.UpdateDialogFilter(
                    id=config.FOLDER_ID,
                    filter=raw_types.DialogFilter(
                        id=config.FOLDER_ID,
                        title=config.FOLDER_NAME,
                        pinned_peers=[],
                        include_peers=input_peers,
                        exclude_peers=[],
                    )
                )
            )
            
            # Link olish
            result = await self.client.invoke(
                functions.chatlists.ExportChatlistInvite(
                    chatlist=raw_types.InputChatlistDialogFilter(filter_id=config.FOLDER_ID),
                    title=config.FOLDER_NAME,
                    peers=input_peers,
                )
            )
            return result.invite.url, None
        except Exception as e:
            logger.error(f"Folder xatosi: {e}")
            return None, str(e)

    async def stop(self):
        if self.client: await self.client.stop()