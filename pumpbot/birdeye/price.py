from typing import Optional
from pumpbot.util.http import http_get
from pumpbot.config import CONFIG,BIRDEYE_API_KEY


async def get_birdeye_price_usd(mint: str) -> Optional[float]:
    if not BIRDEYE_API_KEY:
        return None
    
    url = f"{CONFIG['BIRDEYE_API']}/defi/v3/token/market-data?address={mint}"
    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    r = await http_get(url, headers=headers, timeout=CONFIG["PRICE_TIMEOUT"])
    if r.status_code != 200:
        return None
    price = (r.json().get("data") or {}).get("price")
    return float(price) if price else None
