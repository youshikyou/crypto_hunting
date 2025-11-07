# scripts/test_bundlers_ratio.py
import asyncio
from typing import Optional
from datetime import datetime, timezone

from pumpbot.metrics.bundler import calc_bundlers_ratio_eap
from pumpbot.dex.dexscreener import get_token_pair_from_dexscreener
from pumpbot.util.notify import notify_serverchan
from pumpbot.config import CONFIG

def _s_to_iso(sec: int) -> str:
    return datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

async def main(
    mint: str,
    pair: Optional[str],
    push: bool = True,
):
    """
    Compute wallet-centric Bundlers Ratio for the token mint over the EAP (~8h) window,
    using pumpbot.metrics.bundler.calc_bundlers_ratio_eap.
    """
    # Display-only enrichment from Dexscreener
    pair_info = None
    if not pair:
        try:
            pair_info = await get_token_pair_from_dexscreener(mint)
            pair = str(pair_info.get("pairAddress")) if pair_info else None
        except Exception:
            pair = None

    # Compute via EAP (Bearer token read inside the function)
    res = await calc_bundlers_ratio_eap(mint)

    # Pretty %
    def pct(x: Optional[float]) -> str:
        try:
            return f"{round((x or 0.0) * 100, 2)}%"
        except Exception:
            return "-"

    # Build output text to match fields returned by bundler.py (Axiom version)
    txt = (
        f"Mint: {mint}\n"
        f"Pair (display): {pair or '-'}\n"
        f"Window (EAP): {res.get('window_start', '-')} → {res.get('window_end', '-')}\n"
        f"Min wallets per slot (Axiom): 4\n"
        f"\n"
        f"Unique wallets (all): {res.get('total_wallets', 0)} | "
        f"Bundler wallets: {res.get('bundler_wallets', 0)}\n"
        f"Bundled slots: {res.get('bundled_slots', 0)}\n"
        f"Bundlers Ratio (wallets): {res.get('bundlers_ratio_pct') or pct(res.get('bundlers_ratio'))}\n"
        f"OK: {res.get('ok', False)} | Error: {res.get('error', '-')}\n"
    )

    print(txt)
    if push:
        await notify_serverchan(f"[BUNDLERS TEST] {mint[:6]}...{mint[-4:]}", txt.replace("\n", "\n\n"))

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mint", required=True, help="Token mint address to analyze")
    p.add_argument("--pair", help="Optional pair/pool address (display only)")
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args()

    asyncio.run(main(args.mint, args.pair, push=not args.no_push))
