# pumpbot/watchers/migrated.py
import json, time, asyncio, websockets, httpx
from datetime import datetime
from typing import Optional
from pathlib import Path
import csv


from pumpbot.config import CONFIG, PUMPPORTAL_KEY, BITQUERY_API_KEY
from pumpbot.metrics.bundler import calc_bundlers_ratio_eap
from pumpbot.metrics.gas import calc_total_fees_gmgn_style
from pumpbot.metrics.holders import compute_top_ratio
from pumpbot.metrics.mcap import fast_mcap_usd
from pumpbot.metrics.ttc import compute_ttc_ms, humanize_duration
from pumpbot.dex.dexscreener import get_token_pair_from_dexscreener
from pumpbot.util.notify import notify_serverchan
from pumpbot.chain.rpc import get_client

_SEM = asyncio.Semaphore(4)
EAP = "https://streaming.bitquery.io/eap"


def _to_utc_str(sec: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(sec))

def _iso_to_timestamp(iso: str) -> Optional[int]:
    try:
        # Bitquery gives e.g. "2025-09-14T22:31:05Z"
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None

def _event_ts(ts_raw) -> Optional[int]:
    """
    Normalize portal timestamp (seconds / ms / µs / ISO) to seconds.
    """
    if ts_raw is None:
        return None
    # ISO string?
    if isinstance(ts_raw, str) and not ts_raw.strip().isdigit():
        return _iso_to_timestamp(ts_raw)

    # numeric (or numeric string)
    try:
        n = int(ts_raw)
    except ValueError:
        return None

    # Decide by magnitude/digits
    # >= 1e16: nanoseconds -> s
    # >= 1e14: microseconds -> s
    # >= 1e12: milliseconds -> s
    # >= 1e9 : seconds
    d = len(str(abs(n)))
    if d >= 16:        # ns
        return n // 1_000_000_000
    if d >= 14:        # µs
        return n // 1_000_000
    if d >= 12:        # ms
        return n // 1_000
    if d >= 10:        # s
        return n
    # too small to be a valid epoch; treat as seconds anyway
    return n


CSV_PATH = Path("data/migrated_metrics.csv")

def _ensure_csv_header(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "mint", "pair", "migrated_at_iso", "creation_time_iso", "ttc_human",
                "bundlers_ratio", "bundler_wallets", "total_wallets", "bundled_slots",
                "gas_txn_sol", "gas_dex_sol", "gas_bundle_sol", "gas_txn_cnt", "gas_trade_cnt", "gas_bundle_cnt",
                "mcap_usd", "price_usd", "top10_ratio"
            ])

def _pct(x: float | None) -> str:
    try:
        return f"{(x or 0.0)*100:.2f}%"
    except Exception:
        return "0.00%"

async def _compute_and_report_metrics(
    mint: str,
    *,
    pair_addr: str | None,
    migrated_time_sec: int,
    push: bool = True,
):
    """
    Compute 5 metrics and send + persist:
      - Bundlers Ratio (Axiom-style, EAP)
      - Gas/Fees (GMGN-style parts)
      - Market cap (fast)
      - Top holders ratio (Top-10)
      - TTC (creation -> migrated)
    """
    # 1) TTC (needs ms)
    ttc_ms, birth_ms = await compute_ttc_ms(mint, migrated_time_sec * 1000)
    creation_iso = _to_utc_str(birth_ms//1000) if birth_ms else "-"
    ttc_h = humanize_duration(ttc_ms)

    # 2) parallelize the rest
    client = await get_client()
    bundlers_coro = calc_bundlers_ratio_eap(mint)  # EAP inside, no args
    gas_coro = calc_total_fees_gmgn_style(None, mint_address=mint)
    mcap_coro = fast_mcap_usd(client, mint)
    top10_coro = compute_top_ratio(client, mint, top_n=10)

    bundlers, gas, (mcap_usd, price_usd), top10_ratio = await asyncio.gather(
        bundlers_coro, gas_coro, mcap_coro, top10_coro
    )

    # unpack (defensive defaults)
    bundlers_ratio = float(bundlers.get("bundlers_ratio", 0.0))
    bundlers_pct = bundlers.get("bundlers_ratio_pct") or _pct(bundlers_ratio)
    bundler_wallets = int(bundlers.get("bundler_wallets", 0))
    total_wallets = int(bundlers.get("total_wallets", bundlers.get("total_buying_wallets", 0)))
    bundled_slots = int(bundlers.get("bundled_slots", bundlers.get("bundled_slots_count", 0)))

    txn_sol = float(gas["parts"]["txn_sol"]) if gas and "parts" in gas else 0.0
    dex_sol = float(gas["parts"]["dex_sol"]) if gas and "parts" in gas else 0.0
    bun_sol = float(gas["parts"]["bundle_sol"]) if gas and "parts" in gas else 0.0
    txn_cnt = int(gas["counts"]["txn_count"]) if gas and "counts" in gas else 0
    trade_cnt = int(gas["counts"]["trade_count"]) if gas and "counts" in gas else 0
    bundle_cnt = int(gas["counts"]["bundle_count"]) if gas and "counts" in gas else 0

    mcap_v = float(mcap_usd or 0.0)
    price_v = float(price_usd or 0.0)
    top10_v = float(top10_ratio or 0.0)

    # 3) build message
    msg = (
        f"**MIGRATED METRICS**\n\n"
        f"**Mint:** `{mint}`\n"
        + (f"**Pair:** `{pair_addr}`\n" if pair_addr else "")
        + f"**MigratedAt:** {_to_utc_str(migrated_time_sec)}\n"
        + (f"**CreationTime:** {creation_iso}\n" if birth_ms else "")
        + f"**TTC:** {ttc_h}\n\n"
        f"**Bundlers Ratio (wallets):** {bundlers_pct} "
        f"(bundlers={bundler_wallets}, total={total_wallets}, slots={bundled_slots})\n\n"
        f"**Gas/Fees (SOL):** txn={txn_sol:.6f}, dex={dex_sol:.6f}, bundle={bun_sol:.6f} "
        f"(cnt: txn={txn_cnt}, trade={trade_cnt}, bundle={bundle_cnt})\n\n"
        f"**Mcap:** ${mcap_v:,.0f} | **Price:** ${price_v:.8f}\n"
        f"**Top10 holders:** {_pct(top10_v)}\n"
    )

    # 4) notify
    if push:
        await notify_serverchan(f"[MIGRATED METRICS] {mint[:6]}...{mint[-4:]}", msg)

    # 5) append CSV
    _ensure_csv_header(CSV_PATH)
    with CSV_PATH.open("a", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            mint,
            pair_addr or "",
            _to_utc_str(migrated_time_sec),
            creation_iso,
            ttc_h,
            f"{bundlers_ratio:.6f}",
            bundler_wallets,
            total_wallets,
            bundled_slots,
            f"{txn_sol:.6f}", f"{dex_sol:.6f}", f"{bun_sol:.6f}",
            txn_cnt, trade_cnt, bundle_cnt,
            f"{mcap_v:.6f}", f"{price_v:.10f}",
            f"{top10_v:.6f}",
        ])


# ---------- Fast birth-time resolvers (Bitquery → Dex → RPC) ----------

async def _token_creation(address: str) -> Optional[int]:
    """Earliest on-chain time for address via Bitquery EAP (fast)."""
    if not BITQUERY_API_KEY:
        return None
    q = """
    query($addr:String!){
      Solana{
        Transactions(
          where:{Transaction:{Accounts:{includes:{Address:{is:$addr}}}}}
          orderBy:{ascendingByField:"Block_Time"}
          limit:{count:1}
        ){ Block{ Time } }
      }
    }"""
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {BITQUERY_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=15) as s:
            r = await s.post(EAP, json={"query": q, "variables": {"addr": address}}, headers=headers)
            if r.status_code != 200:
                return None
            rows = (((r.json().get("data") or {}).get("Solana") or {}).get("Transactions")) or []
            if not rows:
                return None
            ts = (rows[0].get("Block") or {}).get("Time")
            return _iso_to_timestamp(ts) if ts else None
    except Exception:
        return None


async def _get_creation_and_t2migrated(mint: str, migrated_time: int) -> tuple[Optional[int], Optional[int]]:

    creation_time = await _token_creation(mint)
    if creation_time is None:
        return None, None
    return max(0, migrated_time - creation_time), creation_time


# ----------------------------- Listener -----------------------------

async def listen_migrated(minutes: int = 10, max_items: int = 20, push: bool = True):
    ws_url = CONFIG["PUMP_WS"]

    got, seen = 0, set()
    timeout_at = time.time() + minutes * 60 if minutes else None
    print(f"[migrated] listening... minutes={minutes} max={max_items}")

    async with websockets.connect(ws_url, ping_interval=20) as ws:
        await ws.send(json.dumps({"method": "subscribeMigration"}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=100)
            if timeout_at and time.time() > timeout_at:
                break
            if max_items and got >= max_items:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=100)
            except asyncio.TimeoutError:
                continue

            data = json.loads(raw) if raw else {}
            print(data)
            mint = data.get("mint") or data.get("token") or data.get("address")
            print(mint)
            if not mint or mint in seen:
                continue
            seen.add(mint)
            got += 1

            print("I am here 2")
            # Pair (for reporting & bundlers)
            pair_info = await get_token_pair_from_dexscreener(mint)
            pair_addr = (pair_info or {}).get("pairAddress")

            print("I am here 3")
            ts_raw = data.get("timestamp") or data.get("ts") or data.get("time") or data.get("blockTime") or int(time.time())
            if ts_raw is None:
                print(f"Warning: No timestamp in data for mint {mint}, using current time")
                ts_raw = int(time.time())

            migrated_time = _event_ts(ts_raw) or int(time.time())

            t2migrated, creation_time = await _get_creation_and_t2migrated(mint, migrated_time)

            async def _run_all():
                async with _SEM:
                    await _compute_and_report_metrics(
                        mint,
                        pair_addr=pair_addr,
                        migrated_time_sec=migrated_time,
                        push=push,
                    )

            asyncio.create_task(_run_all())
            # Optional push for the raw migration event
            if push: 
                msg = (
                    f"**MIGRATED**\n\n"
                    f"**Mint:** `{mint}`\n\n"
                    + (f"**Pair:** `{pair_addr}`\n\n" if pair_addr else "")
                    + f"**MigratedAt:** {_to_utc_str(migrated_time)}\n\n"
                    + (f"**CreationTime:** {_to_utc_str(creation_time)}\n\n" if creation_time is not None else "No creation time")
                    + f"**TTC(created→migrated):** "
                    + (f"{t2migrated} sec" if t2migrated is not None else "No calculation")
                    + "\n"
                )
                await notify_serverchan(f"[MIGRATED] {mint[:6]}...{mint[-4:]}", msg)