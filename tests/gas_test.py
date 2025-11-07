# tests/gas_test.py
import asyncio
from pumpbot.util.notify import notify_serverchan
from pumpbot.dex.dexscreener import retry_get_pair
from pumpbot.metrics.gas import calc_total_fees_gmgn_style


async def main(mint: str, pair: str | None, push: bool = True):
    # Only for display: try to resolve pair (doesn't affect fee calculation)
    if not pair:
        try:
            info = await retry_get_pair(mint)
            pair = str(info.get("pairAddress")) if info else None
        except Exception:
            pair = None

    # New: no since_ms — just compute GMGN-style total fees by mint
    res = await calc_total_fees_gmgn_style(None, mint)
    total = res["total_sol"]
    parts = res["parts"]
    counts = res["counts"]

    txt = (
        f"Mint: {mint}\n"
        f"Pair: {pair or '-'}\n"
        f"Total Fees (SOL): {total}\n"
        f"  - Txn Fees (SOL): {parts['txn_sol']}\n"
        f"  - DEX Trading Fees (SOL): {parts['dex_sol']}\n"
        f"  - Bundle/Tips (SOL): {parts['bundle_sol']}\n"
        f"Counts:\n"
        f"  - Transactions: {counts['txn_count']}\n"
        f"  - Trades: {counts['trade_count']}\n"
        f"  - Bundled: {counts['bundle_count']}\n"
    )
    print(txt)

    if push:
        await notify_serverchan(f"[GAS TEST] {mint[:6]}...{mint[-4:]}", txt.replace("\n", "\n\n"))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mint", required=True, help="Mint address to aggregate fees for")
    p.add_argument("--pair", help="Optional pair address for display")
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args()
    asyncio.run(main(args.mint, args.pair, push=not args.no_push))
