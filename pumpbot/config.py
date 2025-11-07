import os
from dotenv import load_dotenv


load_dotenv()


RPC_URL = os.getenv("RPC_URL")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY", "")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
BITQUERY_API_KEY = os.getenv("BITQUERY_API_KEY", "")
PUMPPORTAL_KEY = os.getenv("PUMPPORTAL_API_KEY", "")


if not RPC_URL:
    raise SystemExit("Please set RPC_URL in .env")


CONFIG = {
"PUMP_WS": "wss://pumpportal.fun/api/data",
"DEX_API": "https://api.dexscreener.com",
"BIRDEYE_API": "https://public-api.birdeye.so",


"HTTP_TIMEOUT": 15,
"PRICE_TIMEOUT": 10,


"PAIR_MAX_RETRIES": 8,
"PAIR_RETRY_SLEEP": 5,


# default windows
"BUNDLE_WINDOW_SEC": 5 * 60,
"ONESHOT_WINDOW_SEC": 60,
}


# program IDs
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
TOKEN_PROGRAM_ID_V1 = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_PROGRAM_ID_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
INCINERATOR = "1nc1nerator11111111111111111111111111111111"