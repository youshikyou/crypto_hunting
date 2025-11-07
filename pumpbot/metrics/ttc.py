# pumpbot/metrics/ttc.py
from __future__ import annotations
from typing import Optional, Dict
from solders.pubkey import Pubkey
from pumpbot.chain.rpc import get_client
import asyncio
import time

# 简易内存缓存（birth_ms 一般不变），可按需换成 Redis/DB
_birth_cache: Dict[str, int] = {}
_cache_lock = asyncio.Lock()
_CACHE_TTL_SEC = 24 * 3600
_cache_ts: Dict[str, float] = {}

async def _get_mint_creation_ms(mint: str) -> Optional[int]:
    """
    遍历 getSignaturesForAddress 直到最早一页，取最早一条的 block_time 作为 mint birth。
    返回毫秒（ms）；拿不到返回 None。
    """
    client = await get_client()
    before = None
    oldest_ms = None
    while True:
        resp = await client.get_signatures_for_address(
            Pubkey.from_string(mint), before=before, limit=1000
        )
        sigs = resp.value or []
        if not sigs:
            break
        last = sigs[-1] 
        if last.block_time is not None:
            oldest_ms = int(last.block_time) * 1000
        before = last.signature
        if len(sigs) < 1000:
            break
    return oldest_ms

async def get_birth_ms_cached(mint: str) -> Optional[int]:
    now = time.time()
    async with _cache_lock:
        ts = _cache_ts.get(mint)
        if mint in _birth_cache and ts and (now - ts) < _CACHE_TTL_SEC:
            return _birth_cache[mint]
    # miss → 查链
    birth = await _get_mint_creation_ms(mint)
    async with _cache_lock:
        if birth:
            _birth_cache[mint] = birth
            _cache_ts[mint] = now
    return birth

def humanize_duration(ms: Optional[int]) -> str:
    if not ms or ms < 0:
        return "-"
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if not parts: parts.append(f"{s}s")
    return " ".join(parts)
    
async def compute_ttc_ms(mint: str, migrated_ms: int) -> tuple[Optional[int], Optional[int]]:
    """
    返回 (ttc_ms, birth_ms)。如果任何一端拿不到，ttc_ms 为 None。
    """
    birth_ms = await get_birth_ms_cached(mint)
    if birth_ms is None or migrated_ms is None:
        return None, birth_ms
    return max(0, migrated_ms - birth_ms), birth_ms
