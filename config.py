# ------------------------------------------------------------------
# [PASTE YOUR SECRETS HERE]
#
# Fill in the following variables with your own sensitive data.
# ------------------------------------------------------------------

# --- Telegram API and Bot Credentials ---
# Get these from my.telegram.org
API_ID = 12345678  # Replace with your API ID
API_HASH = "your_api_hash_here"  # Replace with your API Hash
BOT_TOKEN = "your_bot_token_here"  # Replace with your Bot Token
BOT_USERNAME = "@your_bot_username_here"  # Replace with your bot's username

# --- Database Configuration ---
# Your MongoDB connection string.
MONGO_URI = "your_mongo_uri_here"  # e.g., mongodb+srv://...
MONGO_DB_NAME = "spicybot"

# --- Bot Owner and Support ---
OWNER_ID = 1234567890  # Replace with your Telegram User ID
BUY_BOT_URL = "https://t.me/your_support_bot_or_contact"  # Link for users to buy premium

# --- Other Bot Settings ---
# You can leave these as default or customize them as you see fit.
TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
TOKEN_EXPIRY = 86400  # 24 hours in seconds
NEW_USER_TOKENS = 2
REFERRAL_BONUS = 1
REFRESH_BONUS = 1
PREMIUM_TRIAL_PRICE_INR = 69
PREMIUM_MONTH_PRICE_INR = 199
FREE_USER_SAVE_LIMIT = 100
MENU_EXPIRY_MINUTES = 30
REFRESH_TOKEN_LINK_EXPIRY_SECONDS = 900
NEW_USER_SCROLLS = 500
DAILY_FREE_SCROLLS = 5
FREE_SCROLL_RESET_HOURS = 1
FREE_BATCH_LIMIT = 1
FREE_LIMIT_RESET_HOURS = 24
TOKEN_ACCESS_HOURS = 24

# --- Mini App/Frontend Configuration ---
# This should be the public URL of your separate frontend application.
# If you are deploying the frontend on Render, it will be the URL
# of your 'web' service (e.g., https://your-frontend-name.onrender.com).
# For local development, you might use "http://localhost:3000".
MINI_APP_URL = "http://localhost:3000"  # Replace with your frontend's public URL
