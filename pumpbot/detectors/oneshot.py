from typing import Tuple, Optional
import time
from pumpbot.dex.dexscreener import retry_get_pair
from pumpbot.metrics.holders import compute_top10_holder_ratio
from pumpbot.metrics.bundlers import get_bundle_stats_bitquery
from pumpbot.config import CONFIG

async def check_one_shot(client, mint: str, window_sec: int = CONFIG["ONESHOT_WINDOW_SEC"]) -> Tuple[bool, Optional[float], Optional[float], bool, Optional[str], Optional[int]]:
    pair = await retry_get_pair(mint)
    if not pair:
        return False, None, None, False, None, None
    pair_addr = str(pair.get("pairAddress"))
    created_ms = int(pair.get("pairCreatedAt") or int(time.time()*1000))

    top10 = await compute_top10_holder_ratio(client, mint)

    t1 = int(created_ms/1000)
    t2 = t1 + int(window_sec)
    ratio, has_jito = await get_bundle_stats_bitquery(pair_addr, t1, t2)

    is_oneshot = (top10 is not None and ratio is not None and top10 >= 0.70 and ratio >= 0.70 and has_jito)
    return is_oneshot, top10, ratio, has_jito, pair_addr, created_ms
