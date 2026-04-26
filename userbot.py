"""
userbot.py — Pyrogram UserBot (Pyrogram 2.0.106, Layer 158)

2 ta jild:
  FOLDER_ID_SMALL (10) → < 200 obunachili kanallar
  FOLDER_ID_BIG   (11) → >= 200 obunachili kanallar

Tuzatilgan buglar:
  ✅ BUG1: base.ExportedChatlistInvite da slug yo'q →
           slug = url.split('addlist/')[-1] orqali olinadi
  ✅ BUG2: _create_invite result — result.invite.url (aniq path)
  ✅ BUG3: elif result.url — chiqarib tashlandi (bunday field yo'q)

API mapping (Pyrogram 2.0.106):
  ExportChatlistInvite        → chatlists.ExportedChatlistInvite
    .filter                   → DialogFilter
    .invite                   → base.ExportedChatlistInvite
      .title, .url, .peers    ← URL SHU YERDA

  GetExportedInvites          → chatlists.ExportedInvites
    .invites                  → List[base.ExportedChatlistInvite]
      [i].url                 ← URL SHU YERDA
    .chats, .users

  DeleteExportedInvite(chatlist, slug) → bool
    slug = url.split('addlist/')[-1]   ← SLUG SHU YERDA
"""

import asyncio
import logging

from pyrogram import Client
from pyrogram.errors import PeerIdInvalid, FloodWait, ChannelInvalid
from pyrogram.raw import functions, types as raw_types

import config
import database as db

logger = logging.getLogger(__name__)

MEMBERS_THRESHOLD = 200
FOLDER_ID_SMALL   = 10
FOLDER_ID_BIG     = 11
FOLDER_NAME_SMALL = "🏆 Konkurs (kichik kanallar)"
FOLDER_NAME_BIG   = "🏆 Konkurs (yirik kanallar)"


def _slug_from_url(url: str) -> str | None:
    """
    't.me/addlist/AbCdEf' → 'AbCdEf'
    Slug - bu Linkdan keyin keladigan qism.
    """
    if url and "addlist/" in url:
        slug = url.split("addlist/")[-1].strip("/")
        return slug if slug else None
    return None


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
        InputPeer oladi. Avval ID, keyin username bilan.
        """
        # 1-urinish: channel_id bilan
        try:
            await self.client.get_chat(channel_id)
            return await self.client.resolve_peer(channel_id)
        except FloodWait as e:
            logger.warning(f"FloodWait {e.value}s")
            await asyncio.sleep(e.value + 2)
            return await self._resolve_peer(channel_id, username)
        except (PeerIdInvalid, ChannelInvalid, KeyError):
            pass  # username bilan urinamiz
        except Exception as e:
            logger.warning(f"Peer ID={channel_id}: {e}")

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
                logger.error(f"@{uname} topilmadi: {e}")

        return None

    # ── Obunachilar soni ──────────────────────────────────────────────────────

    async def _get_members_count(self, channel_id: int, username: str | None) -> int:
        """
        Kanal obunachilar sonini qaytaradi.
        Aniqlashning iloji bo'lmasa -1 qaytaradi.
        """
        try:
            target = f"@{username.lstrip('@')}" if username else channel_id
            chat = await self.client.get_chat(target)
            count = getattr(chat, "members_count", None)
            if count is not None:
                return int(count)
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
            return await self._get_members_count(channel_id, username)
        except Exception as e:
            logger.warning(f"members_count ({channel_id}): {e}")
        return -1

    # ── Folder (DialogFilterChatlist) yaratish ────────────────────────────────

    async def _update_folder(self, folder_id: int, title: str, peers: list) -> bool:
        """
        DialogFilterChatlist yaratadi yoki yangilaydi.
        MUHIM: DialogFilterChatlist, DialogFilter emas!
        Faqat DialogFilterChatlist ExportChatlistInvite bilan ishlaydi.
        """
        try:
            await self.client.invoke(
                functions.messages.UpdateDialogFilter(
                    id=folder_id,
                    filter=raw_types.DialogFilterChatlist(
                        id=folder_id,
                        title=title,
                        pinned_peers=[],
                        include_peers=peers,
                    ),
                )
            )
            logger.info(f"Folder '{title}' (id={folder_id}): {len(peers)} ta kanal")
            return True
        except Exception as e:
            logger.error(f"Folder '{title}' yaratish xatolik: {e}")
            return False

    # ── Mavjud invite link olish ──────────────────────────────────────────────

    async def _get_existing_invite(self, folder_id: int) -> str | None:
        """
        GetExportedInvites → chatlists.ExportedInvites
          .invites → List[base.ExportedChatlistInvite]
            [0].url → 'https://t.me/addlist/...'
        """
        try:
            result = await self.client.invoke(
                functions.chatlists.GetExportedInvites(
                    chatlist=raw_types.InputChatlistDialogFilter(filter_id=folder_id)
                )
            )
            invites = getattr(result, "invites", [])
            if invites:
                # invites[0] — base.ExportedChatlistInvite
                url = getattr(invites[0], "url", None)
                if url:
                    logger.info(f"Mavjud link (folder {folder_id}): {url}")
                    return url
        except Exception as e:
            logger.debug(f"Mavjud link yo'q (folder {folder_id}): {e}")
        return None

    # ── Eski linklar o'chirish ────────────────────────────────────────────────

    async def _delete_old_invites(self, folder_id: int):
        """
        Limit (10 ta) oshib ketmasligi uchun eski linklar o'chiriladi.

        TUZATILGAN BUG:
          base.ExportedChatlistInvite da 'slug' field YO'Q!
          Faqat: title, url, peers
          Slug = url.split('addlist/')[-1] orqali olinadi.
        """
        try:
            result = await self.client.invoke(
                functions.chatlists.GetExportedInvites(
                    chatlist=raw_types.InputChatlistDialogFilter(filter_id=folder_id)
                )
            )
            invites = getattr(result, "invites", [])
            for invite in invites:
                url  = getattr(invite, "url", "") or ""
                slug = _slug_from_url(url)   # ← TO'G'RI: url dan slug olish
                if slug:
                    try:
                        await self.client.invoke(
                            functions.chatlists.DeleteExportedInvite(
                                chatlist=raw_types.InputChatlistDialogFilter(
                                    filter_id=folder_id
                                ),
                                slug=slug,
                            )
                        )
                        logger.info(f"Eski link o'chirildi: {slug}")
                    except Exception as e:
                        logger.warning(f"Link o'chirishda xatolik ({slug}): {e}")
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"_delete_old_invites (folder {folder_id}): {e}")

    # ── Yangi invite link yaratish ────────────────────────────────────────────

    async def _create_invite(self, folder_id: int, title: str, peers: list) -> str | None:
        """
        ExportChatlistInvite → chatlists.ExportedChatlistInvite qaytaradi
          .filter → DialogFilter
          .invite → base.ExportedChatlistInvite
            .url  ← URL SHU YERDA

        TUZATILGAN BUG:
          Eski: elif hasattr(result, 'url') — bunday field yo'q
          Yangi: faqat result.invite.url tekshiriladi
        """
        for attempt in range(2):
            try:
                result = await self.client.invoke(
                    functions.chatlists.ExportChatlistInvite(
                        chatlist=raw_types.InputChatlistDialogFilter(
                            filter_id=folder_id
                        ),
                        title=title,
                        peers=peers,
                    )
                )
                # result — chatlists.ExportedChatlistInvite
                # result.invite — base.ExportedChatlistInvite
                # result.invite.url — 'https://t.me/addlist/...'
                invite = getattr(result, "invite", None)
                if invite:
                    url = getattr(invite, "url", None)
                    if url:
                        logger.info(f"Yangi link yaratildi (folder {folder_id}): {url}")
                        return url

                logger.error(f"URL topilmadi. result type: {type(result)}")

            except Exception as e:
                err = str(e).lower()
                # Allaqachon mavjud bo'lsa — mavjud linkni olib qaytaramiz
                if "already" in err or "chatlist_invite" in err:
                    logger.info(f"Link allaqachon mavjud, mavjud link olinmoqda...")
                    return await self._get_existing_invite(folder_id)

                if attempt == 0:
                    logger.warning(
                        f"Link yaratish xatolik (folder {folder_id}, 1-urinish): {e}\n"
                        f"Eski linklar o'chirilmoqda..."
                    )
                    await self._delete_old_invites(folder_id)
                    await asyncio.sleep(1)
                else:
                    logger.error(
                        f"Link yaratish muvaffaqiyatsiz (folder {folder_id}, 2-urinish): {e}"
                    )

        return None

    # ── Asosiy funksiya — 2 ta jild ───────────────────────────────────────────

    async def create_folder_links(self) -> dict:
        """
        Kanallarni obunachilar soniga qarab 2 jildga bo'ladi va link yaratadi.

        Qadam-baqadam:
          1. Har kanal uchun InputPeer olish
          2. Obunachilar sonini aniqlash
          3. < 200  → small_peers
             >= 200 → big_peers
          4. _update_folder (DialogFilterChatlist yaratish)
          5. _get_existing_invite (mavjud link bor?)
          6. _create_invite (yangi link)

        Returns:
            {
                "small":       str | None,
                "big":         str | None,
                "small_count": int,
                "big_count":   int,
            }
        """
        if not self.is_ready:
            logger.error("UserBot tayyor emas.")
            return {}

        channels = db.get_channels()
        if not channels:
            logger.warning("Bazada kanallar yo'q.")
            return {}

        logger.info(f"Jild yaratish boshlandi: {len(channels)} ta kanal")

        small_peers = []
        big_peers   = []

        for ch_id, ch_user, ch_title, _ in channels:
            # 1. Peer olish
            peer = await self._resolve_peer(ch_id, ch_user)
            if not peer:
                logger.warning(f"  ❌ Peer topilmadi: {ch_title} ({ch_id})")
                await asyncio.sleep(0.4)
                continue

            # 2. Obunachilar soni
            count = await self._get_members_count(ch_id, ch_user)
            await asyncio.sleep(0.5)

            # 3. Jildga ajratish
            if count == -1:
                logger.warning(f"  ❓ {ch_title}: son aniqlanmadi → kichik jild")
                small_peers.append(peer)
            elif count < MEMBERS_THRESHOLD:
                logger.info(f"  📁 {ch_title}: {count} → kichik jild")
                small_peers.append(peer)
            else:
                logger.info(f"  📁 {ch_title}: {count} → yirik jild")
                big_peers.append(peer)

        result = {
            "small":       None,
            "big":         None,
            "small_count": len(small_peers),
            "big_count":   len(big_peers),
        }

        # 4. Kichik jild
        if small_peers:
            logger.info(f"Kichik jild yaratilmoqda: {len(small_peers)} ta kanal")
            ok = await self._update_folder(FOLDER_ID_SMALL, FOLDER_NAME_SMALL, small_peers)
            if ok:
                await asyncio.sleep(1)
                link = await self._get_existing_invite(FOLDER_ID_SMALL)
                if not link:
                    link = await self._create_invite(
                        FOLDER_ID_SMALL, FOLDER_NAME_SMALL, small_peers
                    )
                result["small"] = link
                logger.info(f"Kichik jild linki: {link}")

        # 5. Yirik jild
        if big_peers:
            logger.info(f"Yirik jild yaratilmoqda: {len(big_peers)} ta kanal")
            ok = await self._update_folder(FOLDER_ID_BIG, FOLDER_NAME_BIG, big_peers)
            if ok:
                await asyncio.sleep(1)
                link = await self._get_existing_invite(FOLDER_ID_BIG)
                if not link:
                    link = await self._create_invite(
                        FOLDER_ID_BIG, FOLDER_NAME_BIG, big_peers
                    )
                result["big"] = link
                logger.info(f"Yirik jild linki: {link}")

        logger.info(
            f"Jildlar tayyor: "
            f"kichik={result['small_count']}ta({result['small']}), "
            f"yirik={result['big_count']}ta({result['big']})"
        )
        return result

    async def create_folder_link(self) -> str | None:
        """Bitta link kerak bo'lganda ishlatiladi."""
        r = await self.create_folder_links()
        return r.get("big") or r.get("small")
