# pumpbot/metrics/migrated_features.py
from __future__ import annotations
import asyncio, time, inspect
from typing import Optional, Dict, Any, Tuple

from pumpbot.chain.rpc import get_client
from pumpbot.metrics.mcap import fast_mcap_usd
from pumpbot.metrics.holders import compute_top10_holder_ratio
from pumpbot.metrics.bundlers import calc_bundler_share, DEFAULT_BUNDLERS
from pumpbot.metrics.gas import calc_global_gas_fee_sol
from pumpbot.metrics.ttc import compute_ttc_ms
from pumpbot.dex.dexscreener import get_token_pair_from_dexscreener, get_pair_detail

def _now_ms() -> int:
    return int(time.time() * 1000)



async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v

async def _get_client():
    # 兼容 get_client() 可能是 sync 或 async 的两种实现
    c = get_client()
    return await _maybe_await(c)

async def _resolve_pair(mint: str, pair_hint: str | None, retries: int = 3, delay: float = 0.8):
    """
    返回 (resolved_pair_addr, pair_info)。
    优先使用调用方传的 pair_hint；否则用 Dexscreener 通过 mint 解析。
    新迁移的池子可能未立刻被索引，做几个轻量重试。
    """

    if pair_hint:
        try:
            info = await get_pair_detail(pair_hint)
        except Exception:
            info = None
        return pair_hint, info

    last_info = None
    try:
        info = await get_token_pair_from_dexscreener(mint)
        if info and info.get("pairAddress"):
            return info["pairAddress"], info
        last_info = info
    except Exception:
        pass

    return None, last_info

async def _mcap_price(client, mint: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        mcap_usd, price_usd = await fast_mcap_usd(client, mint)
        return mcap_usd, price_usd
    except Exception:
        return None, None

async def _holders(client, mint: str) -> Optional[float]:
    try:
        return await compute_top10_holder_ratio(client, mint)
    except Exception:
        return None

async def _bundlers(address: str, start_ms: int, until_ms: int) -> Tuple[Optional[float], bool, Dict[str, Any]]:
    """
    使用 calc_bundler_share 计算总体占比；再用 DEFAULT_BUNDLERS 子集判断 has_jito。
    address 优先传 pair(池子地址)，没有再回退 mint。
    """
    try:
        overall = await calc_bundler_share(None, address, start_ms, until_ms=until_ms)
        ratio = overall.get("ratio_by_count", 0.0)

        jito = await calc_bundler_share(None, address, start_ms, until_ms=until_ms, bundlers=DEFAULT_BUNDLERS)
        has_jito = (jito.get("bundle_count", 0) or 0) > 0

        return ratio, has_jito, overall
    except Exception:
        return None, False, {}

async def _gas(mint: str, start_ms: int) -> Optional[float]:
    try:
        return await calc_global_gas_fee_sol(None, mint, start_ms)
    except Exception:
        return None

async def _pair_info(pair: Optional[str], mint: str) -> Optional[Dict[str, Any]]:
    try:
        if pair:
            # 已知 pair，就直接用后续 reporter 细节
            info = await get_pair_from_pair(pair)
            return info
        # 不传 pair → 尝试用 mint 去 Dexscreener 查主 pair
        return await get_token_pair_from_dexscreener(mint)
    except Exception:
        return None

# 兼容不同 dexscreener 工具函数命名（如果你另有 retry_get_pair，可按需替换）
async def get_pair_from_pair(pair_addr: str) -> Optional[Dict[str, Any]]:
    # 你已有 get_pair_detail 可直接用，这里做个薄封装
    from pumpbot.dex.dexscreener import get_pair_detail
    try:
        return await get_pair_detail(pair_addr)
    except Exception:
        return None

async def compute_migrated_features(
    mint: str,
    *,
    pair: Optional[str] = None,
    migrated_ms: Optional[int] = None,
    start_ms: Optional[int] = None,
    until_ms: Optional[int] = None,
    window_mode: str = "since_birth",  # "after_migrated" | "since_birth" | "last24h"
) -> Dict[str, Any]:
    """
    返回结构：
    {
      "mint": str, "pair": Optional[str],
      "timestamps": {"birth_ms","migrated_ms","start_ms","until_ms","ttc_ms"},
      "market": {"price_usd","mcap_usd","pair_info"},
      "holders": {"top10_ratio"},
      "bundlers": {"ratio_by_count","has_jito","summary":{...}},
      "gas": {"gas_sol"},
      "window_mode": str,
      "address_for_bundler": str
    }
    """
    now = _now_ms()
    if until_ms is None:
        until_ms = now

    # 先补全 birth/ttc
    ttc_ms = None
    birth_ms = None
    if migrated_ms is not None:
        ttc_ms, birth_ms = await compute_ttc_ms(mint, migrated_ms)

    # 决策窗口起点
    if start_ms is None:
        if window_mode == "after_migrated" and migrated_ms:
            start_ms = migrated_ms
        elif window_mode == "since_birth" and birth_ms:
            start_ms = birth_ms
        else:
            start_ms = until_ms - 24 * 3600 * 1000  # last24h

    client = await _get_client()
    
    resolved_pair, pair_info = await _resolve_pair(mint, pair)

    addr_for_bundler = resolved_pair or mint

    # 并发拿数
    (mcap_usd, price_usd), top10_ratio, (bundler_ratio, has_jito, bundler_summary), gas_sol= await asyncio.gather(
        _mcap_price(client, mint),
        _holders(client, mint),
        _bundlers(addr_for_bundler, start_ms, until_ms),
        _gas(mint, start_ms),
    )

    # 关闭 client（如果有 close 且是可等待的）
    try:
        closer = getattr(client, "close", None)
        if closer:
            v = closer()
            if inspect.isawaitable(v):
                await v
    except Exception:
        pass

    return {
        "mint": mint,
        "pair": resolved_pair,
        "timestamps": {
            "birth_ms": birth_ms,
            "migrated_ms": migrated_ms,
            "start_ms": start_ms,
            "until_ms": until_ms,
            "ttc_ms": ttc_ms,
        },
        "market": {
            "price_usd": price_usd,
            "mcap_usd": mcap_usd,
            "pair_info": pair_info,
        },
        "holders": {
            "top10_ratio": top10_ratio,
        },
        "bundlers": {
            "ratio_by_count": (None if bundler_ratio is None else float(bundler_ratio)),
            "has_jito": has_jito,
            "summary": bundler_summary,
        },
        "gas": {
            "gas_sol": gas_sol,
        },
        "window_mode": window_mode,
        "address_for_bundler": addr_for_bundler,
    }
