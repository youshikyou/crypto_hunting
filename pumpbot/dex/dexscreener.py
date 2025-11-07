from typing import Optional
from pumpbot.util.http import http_get
from pumpbot.config import CONFIG


async def get_token_pair_from_dexscreener(mint: str) -> Optional[dict]:
    url = f"{CONFIG['DEX_API']}/token-pairs/v1/solana/{mint}"
    r = await http_get(url)
    if r.status_code != 200:
        return None
    arr = r.json()
    if not isinstance(arr, list):
        return None
    def _dexid(p: dict) -> str:
        return str(p.get("dexId", "")).lower()
    
    pumps = [p for p in arr if _dexid(p) in ("pumpswap", "pump", "pumpswapamm")]
    if not pumps:
        pumps = [p for p in arr if _dexid(p) == "raydium"]
    
    if not pumps:
        return None
    
    pumps.sort(key=lambda x: x.get("pairCreatedAt", 0), reverse=True)
    return pumps[0]


async def retry_get_pair(mint: str) -> Optional[dict]:
    from asyncio import sleep
    pair = await get_token_pair_from_dexscreener(mint)
    retries = 0
    while not pair and retries < CONFIG["PAIR_MAX_RETRIES"]:
        await sleep(CONFIG["PAIR_RETRY_SLEEP"])
        pair = await get_token_pair_from_dexscreener(mint)
        retries += 1
    return pair


async def get_pair_detail(pair_addr: str) -> Optional[dict]:
    url = f"{CONFIG['DEX_API']}/latest/dex/pairs/solana/{pair_addr}"
    r = await http_get(url)
    if r.status_code != 200:
        return None
    data = r.json()
    return (data.get("pairs") or [None])[0]