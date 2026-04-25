import os

# ════════════════════════════════════════════
#   SHU YERGA O'Z MA'LUMOTLARINGIZNI YOZING
# ════════════════════════════════════════════

BOT_TOKEN      = os.environ.get("BOT_TOKEN",      "YOUR_BOT_TOKEN")
API_ID         = int(os.environ.get("API_ID",     "12345"))
API_HASH       = os.environ.get("API_HASH",       "YOUR_API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING", "YOUR_SESSION_STRING")
ADMIN_ID       = int(os.environ.get("ADMIN_ID",   "123456789"))

# Render port
PORT = int(os.environ.get("PORT", 10000))

# Majburiy obuna (1 ta kanal + 1 ta guruh)
REQUIRED = [
    {
        "username": "ortiqboyovichch",
        "title":    "Ortiqboyovich",
        "url":      "https://t.me/ortiqboyovichch",
        "type":     "kanal",
    },
    {
        "username": "jildgaqoshil",
        "title":    "Jildga Qo'shil",
        "url":      "https://t.me/jildgaqoshil",
        "type":     "guruh",
    },
]

# Folder sozlamalari
FOLDER_ID   = 10
FOLDER_NAME = "Konkurs Jildi 📁"
