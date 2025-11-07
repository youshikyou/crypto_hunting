# pumpbot/metrics/holders.py
import os
import math
import httpx
from typing import Optional, List, Dict, Tuple
from pumpbot.config import BIRDEYE_API_KEY
from pumpbot.chain.token_accounts import filter_user_wallets  

BASE = "https://public-api.birdeye.so/defi/v3/token/holder"


def _headers() -> dict:
    if not BIRDEYE_API_KEY:
        raise RuntimeError("BIRDEYE_API_KEY not set")
    return {
        "accept": "application/json",
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain": "solana",
    }

async def fetch_top_holders_birdeye(
    mint: str,
    *,
    limit: int = 50,          # 1..100
    offset: int = 0,
    ui_amount_mode: str = "scaled",  # scaled -> 用 ui_amount；raw -> 用 amount
) -> Tuple[List[Dict], Optional[int]]:
    holders: List[Dict] = []

    async with httpx.AsyncClient(timeout=20) as s:
        params = {
            "address": mint,
            "offset": offset,
            "limit": limit,
            "ui_amount_mode": ui_amount_mode,
        }
        r = await s.get(BASE, headers=_headers(), params=params)
        r.raise_for_status()
        j = r.json()

    data = j.get("data") or {}
    items = data.get("items") or []

    for it in items:
        addr = it.get("owner") or it.get("address")  # Birdeye v3 用 owner
        if not addr:
            continue

        if ui_amount_mode == "scaled":
            bal = it.get("ui_amount")
            if bal is None:
                # 兜底：自己按 decimals 折算
                amt = it.get("amount")
                dec = it.get("decimals")
                try:
                    bal = int(amt) / (10 ** int(dec))
                except Exception:
                    bal = 0.0
        else:
            # raw：直接用 amount（整型字符串）
            try:
                bal = float(it.get("amount") or 0)
            except Exception:
                bal = 0.0

        holders.append({"address": addr, "balance": float(bal)})

    # 防御性排序（接口通常已按余额降序）
    holders.sort(key=lambda x: x["balance"], reverse=True)
    return holders

async def compute_top_ratio(client, mint: str, top_n: int = 10) -> Optional[float]:
    """Top-N 持币占比（返回 0..1）。"""
    from pumpbot.metrics.mcap import get_total_supply_ui

    # 拉多一点，避免过滤掉 PDA 后不够 top_n
    limit = max(50, top_n * 3)
    offset = 0
    picked: List[Dict] = []

    while len(picked) < top_n:
        chunk = await fetch_top_holders_birdeye(mint, limit=limit, offset=offset, ui_amount_mode="scaled")
        if not chunk:
            break

        owners = [h["address"] for h in chunk]
        allowed = set(await filter_user_wallets(owners))

        picked.extend([h for h in chunk if h["address"] in allowed])
        if len(chunk) < limit:
            break
        offset += limit

    if not picked:
        return None

    supply_ui, _ = await get_total_supply_ui(client, mint)
    if supply_ui <= 0:
        return None

    top = picked[:top_n]
    top_sum = sum(h["balance"] for h in top)
    return float(top_sum / supply_ui)