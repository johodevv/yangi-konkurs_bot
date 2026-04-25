import os

# =============================================
# SHU YERGA O'Z MA'LUMOTLARINGIZNI KIRITING
# =============================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH_HERE")
SESSION_STRING = os.environ.get("SESSION_STRING", "YOUR_SESSION_STRING_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

# Render port (default 10000)
PORT = int(os.environ.get("PORT", 10000))

# Folder ID (1-255 orasida, ixtiyoriy son)
FOLDER_ID = 10
FOLDER_NAME = "Konkurs Jildi 📁"
