# pumpbot/watchers/migrated.py
# Purpose: detect "migration" across the broader Solana meme space:
#  - Source A: PumpPortal (Pump.fun + BONK)
#  - Source B: On-chain AMM pool-init/liquidity events via Solana logsSubscribe
#
# Output: notify_serverchan with ONLY name + mint (name may be "-")

import json
import time
import asyncio
from typing import Optional, AsyncIterator

import websockets

from pumpbot.config import CONFIG, RPC_URL
from pumpbot.util.notify import notify_serverchan

PUMP_WS = CONFIG["PUMP_WS"]  # "wss://pumpportal.fun/api/data"

# ====== Configure your AMM programs (FILL THESE) ======
# Put the exact program IDs you want to watch. Examples (replace with your up-to-date IDs):
AMM_PROGRAM_IDS = [
    # Raydium CPMM / AMM
    # "AMMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    # Raydium CLMM
    # "CLMMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    # Orca Whirlpool
    # "whirLbMiW9xxx...replace_me...", 
    # Meteora AMM V2
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB",  
]

# If you don’t want to list programs yet, leave it empty; the AMM watcher will be skipped.

# ====== Helpers ======

def _now() -> float:
    return time.time()

def _slice_mint(m: str) -> str:
    return f"{m[:6]}...{m[-4:]}" if len(m) > 10 else m

def _norm_name(x) -> str:
    return (x or "-").strip() or "-"

def _dedupe_key(ev: dict) -> str:
    # Prefer transaction signature if present; else mint
    sig = ev.get("signature") or ev.get("tx") or ev.get("txHash")
    if sig:
        return f"sig:{sig}"
    mint = ev.get("mint") or ev.get("token") or ev.get("tokenAddress") or ev.get("address") or "-"
    return f"mint:{mint}"

# ====== Source A: PumpPortal (Pump.fun + BONK) ======

async def source_pumpportal() -> AsyncIterator[dict]:
    """Yield {'mint': str, 'name': str, 'signature': Optional[str]} for migrate events."""
    async with websockets.connect(PUMP_WS) as ws:
        await ws.send(json.dumps({"method": "subscribeMigration"}))
        # print("[pumpportal] subscribed")

        while True:
            raw = await ws.recv()
            try:
                obj = json.loads(raw)
            except Exception:
                continue

            payload = obj.get("data") if isinstance(obj.get("data"), dict) else obj
            etype = (payload.get("type") or payload.get("event") or "").lower()
            if "migrat" not in etype and '"migrate"' not in raw.lower():
                # Not a migration event
                continue

            mint = (
                payload.get("mint")
                or payload.get("token")
                or payload.get("tokenAddress")
                or payload.get("address")
            )
            if not mint:
                continue

            name = _norm_name(payload.get("name"))
            sig = payload.get("signature") or payload.get("tx") or payload.get("txHash")
            yield {"mint": mint, "name": name, "signature": sig, "src": "pumpportal"}

# ====== Source B: On-chain AMM logs (broad coverage) ======

async def _rpc_ws(method: str, params) -> AsyncIterator[dict]:
    """Simple JSON-RPC WS client that yields notifications."""
    # RPC_URL from your .env should support websockets (wss://...) for logsSubscribe
    # If your RPC URL is http(s), swap in the corresponding wss endpoint from your provider.
    if RPC_URL.startswith("http"):
        ws_url = RPC_URL.replace("https://", "wss://").replace("http://", "ws://")
    else:
        ws_url = RPC_URL

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}))
        # ack
        _ = await ws.recv()

        while True:
            raw = await ws.recv()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            # notifications carry "method":"logsNotification" etc.
            if isinstance(msg, dict) and "params" in msg:
                yield msg["params"]

def _maybe_extract_pool_event(logs: list[str]) -> Optional[dict]:
    """
    Very light heuristic: detect pool init or first LP add from log lines.
    This is intentionally minimal; different AMMs phrase logs differently.
    Adjust these substrings to your target programs.
    """
    text = "\n".join(logs or [])
    # Common hints (customize as needed):
    hints = [
        "initialize pool",
        "init pool",
        "initialize_pool",
        "pool created",
        "create pool",
        "open position",        # CLMM
        "increase liquidity",   # CLMM
        "add liquidity",        # CPMM
    ]
    if any(h in text.lower() for h in hints):
        return {"hint": "pool"}
    return None

async def source_amm_logs() -> AsyncIterator[dict]:
    """
    Subscribe to logs for known AMM program IDs and infer 'migration'
    when we see pool init / first liquidity style logs.
    """
    if not AMM_PROGRAM_IDS:
        return  # nothing to watch

    # One subscription per program (simplest & lean)
    tasks = []
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def _watch_program(pid: str):
        # logsSubscribe with mentions=pid (program logs)
        params = [{"mentions": [pid]}, {"commitment": "confirmed"}]
        async for notif in _rpc_ws("logsSubscribe", params):
            value = notif.get("result", {}).get("value", {})
            logs = value.get("logs") or []
            sig = value.get("signature")
            # naive detect
            hit = _maybe_extract_pool_event(logs)
            if not hit:
                continue
            # We usually need to resolve the mint(s) from accounts in the tx;
            # keep it lean: we rely on upstream indexers to post a human-friendly line.
            # If your RPC supports enhanced logs with accounts, decode here.
            #
            # Placeholder: try to spot a 32-44 char base58-ish token in logs.
            # If we can't, emit without mint; your downstream can enrich.
            mint = None
            for line in logs:
                # very rough pattern; replace with proper parser if you want
                parts = line.split()
                for p in parts:
                    if 32 <= len(p) <= 44 and p.isalnum() and p[0].isupper():
                        mint = p
                        break
                if mint:
                    break

            yield_ev = {"mint": mint or "-", "name": "-", "signature": sig, "src": "amm"}
            await queue.put(yield_ev)

    for pid in AMM_PROGRAM_IDS:
        tasks.append(asyncio.create_task(_watch_program(pid)))

    try:
        while True:
            ev = await queue.get()
            yield ev
    finally:
        for t in tasks:
            t.cancel()

# ====== Coordinator ======

async def listen_migrated(
    minutes: Optional[int] = None,
    max_items: Optional[int] = None,
    push: bool = True,
) -> None:
    """
    Run both sources and notify on first time we see a mint.
    Only send **name + mint**.
    """
    timeout_at = _now() + minutes * 60 if minutes and minutes > 0 else None
    sent = 0
    seen: set[str] = set()

    async def _pump():
        async for ev in source_pumpportal():
            yield ev

    async def _amm():
        async for ev in source_amm_logs():
            yield ev

    async def _merge():
        tasks = []
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def _push(src_iter):
            async for item in src_iter:
                await queue.put(item)

        tasks.append(asyncio.create_task(_push(_pump())))
        tasks.append(asyncio.create_task(_push(_amm())))

        try:
            while True:
                item = await queue.get()
                yield item
        finally:
            for t in tasks:
                t.cancel()

    async for ev in _merge():
        if timeout_at and _now() >= timeout_at:
            print("[migrated] time limit reached, exit.")
            return
        if max_items is not None and sent >= max_items:
            print("[migrated] max items reached, exit.")
            return

        key = _dedupe_key(ev)
        if key in seen:
            continue
        seen.add(key)

        mint = ev.get("mint") or "-"
        name = _norm_name(ev.get("name"))

        line = f"[MIGRATED] name={name} mint={mint}"
        print(line)

        if push:
            try:
                title = f"[MIGRATED] {name} {_slice_mint(mint)}"
                md = f"**Name:** {name}\n**Mint:** `{mint}`"
                await notify_serverchan(title, md)
            except Exception as e:
                print("[migrated] notify failed:", e)

        sent += 1

        if timeout_at and _now() >= timeout_at:
            print("[migrated] time limit reached, exit.")
            return
        if max_items is not None and sent >= max_items:
            print("[migrated] max items reached, exit.")
            return
