"""

import os
import json
import time
import math
import asyncio
from typing import Optional, Dict, Tuple

import httpx
import websockets
from dotenv import load_dotenv

from solana.rpc.async_api import AsyncClient
from solana.publickey import PublicKey

load_dotenv()

"""
Optimized version:
- Rate limiting: Semaphore for concurrent handles (max 2), sleep 1s per handle.
- Notify only on PASS (configurable).
- One-shot detection: Check initial trades for single large Jito buy.
- Error handling: Retry on API fail, logging.
- Bitquery optional.
"""

CONFIG = {
    # Filters
    "MIN_MCAP_USD": 100_000,
    "MAX_MCAP_USD": 250_000,
    "MAX_GLOBAL_GAS_SOL": 10.0,
    "BUNDLE_WINDOW_SEC": 5 * 60,
    "MIN_BUNDLE_RATIO": 0.20,

    # One-shot detection
    "ONE_SHOT_WINDOW_SEC": 5,  # Check first 5s after creation
    "ONE_SHOT_MIN_SOL": 1.0,   # Min buy amount for one-shot
    "ONE_SHOT_MIN_HOLDING": 0.10,  # Min holding ratio (10%)
    "SKIP_ONE_SHOT": True,     # Skip notify if one-shot detected
    "NOTIFY_ONLY_PASS": True,  # Only notify on PASS status

    # Endpoints
    "PUMP_WS": "wss://pumpportal.fun/api/data",
    "DEX_API": "https://api.dexscreener.com",
    "BIRDEYE_API": "https://public-api.birdeye.so",

    # Misc
    "PRICE_TIMEOUT": 10,
    "HTTP_TIMEOUT": 15,
    "MAX_RETRIES": 3,  # For pool lookup
    "HANDLE_DELAY_SEC": 1,  # Delay per handle to rate limit
    "MAX_CONCURRENT": 2,  # Max concurrent handle_migration
}

RPC_URL = os.getenv("RPC_URL")
BIRDEYE_KEY = os.getenv("BIRDEYE_API_KEY", "")
BITQUERY_API_KEY = os.getenv("BITQUERY_API_KEY", "")
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY", "")
PUMPPORTAL_KEY = os.getenv("PUMPPORTAL_API_KEY", "")

if not RPC_URL:
    raise SystemExit("Please set RPC_URL in .env")

client = AsyncClient(RPC_URL, commitment="confirmed")
seen: set[str] = set()
semaphore = asyncio.Semaphore(CONFIG["MAX_CONCURRENT"])

# -------------------------- helpers --------------------------

async def http_get(url: str, headers: dict | None = None, timeout: int = CONFIG["HTTP_TIMEOUT"]):
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as s:
        return await s.get(url)

async def http_post(url: str, data: dict, headers: dict | None = None, timeout: int = CONFIG["HTTP_TIMEOUT"]):
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as s:
        return await s.post(url, data=data)

# -------------------------- providers --------------------------

async def get_total_supply(mint: str) -> Tuple[float, int]:
    info = await client.get_token_supply(PublicKey(mint))
    val = info.value
    dec = int(val.decimals)
    amt = float(val.amount) / (10 ** dec)
    return amt, dec

async def get_birdeye_price_usd(mint: str) -> Optional[float]:
    if not BIRDEYE_KEY:
        return None
    url = f"{CONFIG['BIRDEYE_API']}/defi/v3/token/market-data?address={mint}"
    headers = {"X-API-KEY": BIRDEYE_KEY}
    try:
        r = await http_get(url, headers=headers, timeout=CONFIG["PRICE_TIMEOUT"])
        if r.status_code != 200:
            return None
        price = (r.json().get("data") or {}).get("price")
        return float(price) if price else None
    except Exception as e:
        print(f"Birdeye error: {e}")
        return None

async def get_token_pair_from_dexscreener(mint: str) -> Optional[dict]:
    url = f"{CONFIG['DEX_API']}/token-pairs/v1/solana/{mint}"
    try:
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
    except Exception as e:
        print(f"DexScreener error: {e}")
        return None

async def fast_mcap_usd(mint: str) -> Tuple[Optional[float], Optional[float]]:
    supply, _ = await get_total_supply(mint)
    be = await get_birdeye_price_usd(mint)
    if be and supply > 0:
        return be * supply, be
    pair = await get_token_pair_from_dexscreener(mint)
    price = float(pair.get("priceUsd") or 0) if pair else 0
    if price > 0 and supply > 0:
        return price * supply, price
    return None, None

async def calc_global_gas_fee_sol(pair_address: str, since_ms: int) -> float:
    addr = PublicKey(pair_address)
    before = None
    total = 0
    try:
        while True:
            sigs = await client.get_signatures_for_address(addr, before=before, limit=1000)
            if len(sigs.value) == 0:
                break
            for sig in sigs.value:
                before = sig.signature
                if sig.block_time and (sig.block_time * 1000) < since_ms:
                    return total / 1e9
                tx = await client.get_transaction(sig.signature)
                fee = tx.value.meta.fee if (tx.value and tx.value.meta) else 0
                total += fee
            await asyncio.sleep(0.04)
        return total / 1e9
    except Exception as e:
        print(f"Gas calc error: {e}")
        return 0.0

async def get_bundle_ratio_bitquery(pair_address: str, start_sec: int, end_sec: int) -> Optional[float]:
    if not BITQUERY_API_KEY:
        return None
    q = """
    query($addr: String!, $t1: DateTime, $t2: DateTime) {
      Solana {
        Transactions(where: {Block: {Time: {since: $t1, till: $t2}}, AnyToAccount: {is: $addr}}){ Count }
        Transactions(where: {Block: {Time: {since: $t1, till: $t2}}, AnyToAccount: {is: $addr}, Bundles: {Any: {BundleId: {not: null}}}}){ Count }
      }
    }
    """
    headers = {"Content-Type": "application/json", "X-API-KEY": BITQUERY_API_KEY}
    body = {
        "query": q,
        "variables": {
            "addr": pair_address,
            "t1": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_sec)),
            "t2": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_sec)),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers) as s:
            r = await s.post("https://streaming.bitquery.io/graphql", json=body)
        if r.status_code != 200:
            return None
        arr = ((r.json().get("data") or {}).get("Solana") or {}).get("Transactions") or []
        total = int((arr[0] or {}).get("Count", 0)) if len(arr) > 0 else 0
        bundled = int((arr[1] or {}).get("Count", 0)) if len(arr) > 1 else 0
        return (bundled / total) if total > 0 else 0.0
    except Exception as e:
        print(f"Bitquery error: {e}")
        return None

async def check_one_shot_buy(pair_addr: str, created_ms: int, mint: str) -> bool:
    addr = PublicKey(pair_addr)
    supply, _ = await get_total_supply(mint)
    try:
        sigs = await client.get_signatures_for_address(addr, limit=50)  # Limit to recent for efficiency
        for sig in sigs.value:
            if sig.block_time and (sig.block_time * 1000 > created_ms + CONFIG["ONE_SHOT_WINDOW_SEC"] * 1000):
                continue  # Skip if outside window
            tx = await client.get_transaction(sig.signature, commitment="confirmed")
            if not tx.value or not tx.value.meta:
                continue
            # Check for Jito (log messages contain "Jito")
            logs = tx.value.meta.log_messages or []
            is_jito = any("Jito" in log for log in logs)
            fee_sol = tx.value.meta.fee / 1e9
            if not is_jito or fee_sol < 0.01:  # Assume Jito tip > 0.01 SOL
                continue
            # Calculate SOL spent by signer (exclude fee)
            signer = tx.value.transaction.message.account_keys[0]  # First key is signer
            pre_balances = tx.value.meta.pre_balances
            post_balances = tx.value.meta.post_balances
            signer_idx = next((i for i, key in enumerate(tx.value.transaction.message.account_keys) if key == signer), None)
            if signer_idx is None:
                continue
            sol_spent = (pre_balances[signer_idx] - post_balances[signer_idx] - tx.value.meta.fee) / 1e9
            if sol_spent < CONFIG["ONE_SHOT_MIN_SOL"]:  # Check SOL spent
                continue
            # Check post balances for holding ratio
            post_bal = tx.value.meta.post_token_balances
            for bal in post_bal:
                if str(bal.mint) == mint and bal.ui_token_amount.ui_amount > 0:
                    holding_ratio = bal.ui_token_amount.ui_amount / supply
                    if holding_ratio >= CONFIG["ONE_SHOT_MIN_HOLDING"]:
                        print(f"One-shot detected: Address {bal.owner} holds {holding_ratio*100:.2f}% with {sol_spent:.2f} SOL spent")
                        return True
            await asyncio.sleep(0.04)
        return False
    except Exception as e:
        print(f"One-shot check error: {e}")
        return False

# -------------------------- notifier --------------------------

async def notify_serverchan(title: str, content_md: str):
    if not SERVERCHAN_KEY:
        print("[WARN] SERVERCHAN_KEY not set; skip push")
        return
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    data = {"title": title, "desp": content_md}
    try:
        r = await http_post(url, data)
        print("Server酱响应:", r.status_code, r.text[:200])
    except Exception as e:
        print("Server酱推送失败:", e)

# -------------------------- handler --------------------------

async def handle_migration(mint: str):
    async with semaphore:
        await asyncio.sleep(CONFIG["HANDLE_DELAY_SEC"])  # Rate limit
        if mint in seen:
            return
        seen.add(mint)
        print("[MIGRATION]", mint)

        # 1) Find pool with retries
        pair = await get_token_pair_from_dexscreener(mint)
        retries = 0
        while not pair and retries < CONFIG["MAX_RETRIES"]:
            await asyncio.sleep(5)
            pair = await get_token_pair_from_dexscreener(mint)
            retries += 1
        if not pair:
            print("  - no pool yet, skip", mint)
            return

        pair_addr = str(pair.get("pairAddress"))
        created_ms = int(pair.get("pairCreatedAt") or int(time.time() * 1000))

        # 2) Market cap
        mcap, price_usd = await fast_mcap_usd(mint)
        if not mcap or not price_usd:
            print("  - no price/mcap, skip")
            return

        # 3) Gas paid
        gas_paid = await calc_global_gas_fee_sol(pair_addr, created_ms)

        # 4) One-shot check
        is_one_shot = await check_one_shot_buy(pair_addr, created_ms, mint)
        if CONFIG["SKIP_ONE_SHOT"] and is_one_shot:
            print("  - One-shot detected, skip notify")
            return

        # 5) Bundle ratio (optional)
        bundle_ratio = None
        if BITQUERY_API_KEY:
            t1 = int(created_ms / 1000)
            bundle_ratio = await get_bundle_ratio_bitquery(pair_addr, t1, t1 + CONFIG["BUNDLE_WINDOW_SEC"])

        # 6) Filters
        ok_mcap = CONFIG["MIN_MCAP_USD"] <= mcap <= CONFIG["MAX_MCAP_USD"]
        ok_gas = gas_paid < CONFIG["MAX_GLOBAL_GAS_SOL"]
        ok_bundle = True if bundle_ratio is None else (bundle_ratio >= CONFIG["MIN_BUNDLE_RATIO"])

        status = "PASS" if (ok_mcap and ok_gas and ok_bundle) else "CANDIDATE"

        # 7) Notify only if PASS or configured
        if CONFIG["NOTIFY_ONLY_PASS"] and status != "PASS":
            print("  - Candidate, skip notify")
            return

        ds_url = f"https://dexscreener.com/solana/{pair_addr}"
        title = f"[{status}] Migrated token: {mint[:6]}...{mint[-4:]}"
        md = (
            f"**Mint:** `{mint}`\n\n"
            f"**Pair:** `{pair_addr}`\n\n"
            f"**Price:** ${price_usd:,.6f}\n\n"
            f"**MCap (est):** ${mcap:,.0f}  (range: {CONFIG['MIN_MCAP_USD']:,}–{CONFIG['MAX_MCAP_USD']:,})\n\n"
            f"**Global Gas Fee Paid:** {gas_paid:.3f} SOL  (max < {CONFIG['MAX_GLOBAL_GAS_SOL']})\n\n"
            f"**Bundle Ratio:** {('N/A' if bundle_ratio is None else f'{bundle_ratio*100:.1f}%')}  (min ≥ {CONFIG['MIN_BUNDLE_RATIO']*100:.0f}% if enabled)\n\n"
            f"**One-Shot Detected:** {'Yes' if is_one_shot else 'No'}\n\n"
            f"**DexScreener:** {ds_url}\n\n"
            f"— sent at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
        )
        await notify_serverchan(title, md)

# -------------------------- WS loop --------------------------

async def main():
    ws_url = CONFIG["PUMP_WS"]
    if PUMPPORTAL_KEY:
        sep = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{sep}api-key={PUMPPORTAL_KEY}"

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                print("WS connected:", ws_url)
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    mint = data.get("mint") or data.get("token") or data.get("address")
                    if mint:
                        asyncio.create_task(handle_migration(mint))
        except Exception as e:
            print("WS error:", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())

"""