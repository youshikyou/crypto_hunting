import asyncio
from pumpbot.metrics.gas import calc_total_fees_fast_helius

MINT = "3MBqhdYrN4p5Qgpc4KvMeBEQokZc4uxfbyNonzEKm6PN"

async def main():
    res = await calc_total_fees_fast_helius(None, MINT, max_signatures=3000)
    print("Mint:", MINT)
    print("Txns scanned:", res["counts"]["txns"])
    print("Base+priority (SOL):", res["parts"]["txn_sol"])
    print("Jito tips (SOL):", res["parts"]["tip_sol"])
    print("TOTAL (SOL):", res["total_sol"])

asyncio.run(main())