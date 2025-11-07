from typing import Tuple, Optional
from solders.pubkey import Pubkey
from pumpbot.dex.dexscreener import get_token_pair_from_dexscreener
from pumpbot.birdeye.price import get_birdeye_price_usd


async def get_total_supply_ui(client, mint: str) -> tuple[float, int]:
    info = await client.get_token_supply(Pubkey.from_string(mint))
    val = info.value
    dec = int(val.decimals)
    amt = float(val.amount) / (10 ** dec)
    return amt, dec



async def fast_mcap_usd(client, mint: str) -> Tuple[Optional[float], Optional[float]]:
    supply, _ = await get_total_supply_ui(client, mint)
    be = await get_birdeye_price_usd(mint)
    if be and supply > 0:
        return be * supply, be
    pair = await get_token_pair_from_dexscreener(mint)
    price = float(pair.get("priceUsd") or 0) if pair else 0
    if price > 0 and supply > 0:
        return price * supply, price
    return None, None
