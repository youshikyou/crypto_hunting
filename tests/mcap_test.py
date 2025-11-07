import asyncio
from pumpbot.chain.rpc import get_client
from pumpbot.metrics.mcap import fast_mcap_usd, get_total_supply_ui
from pumpbot.dex.dexscreener import get_token_pair_from_dexscreener
from pumpbot.util.notify import notify_serverchan


async def main(mint: str, push: bool = True):
    client = get_client()
    mcap, price = await fast_mcap_usd(client, mint)
    supply, dec = await get_total_supply_ui(client, mint)
    pair = await get_token_pair_from_dexscreener(mint)
    pair_addr = (pair or {}).get("pairAddress")
    created_ms = (pair or {}).get("pairCreatedAt")
    txt = (
        f"Mint: {mint}\n"
        f"Price(USD): {price}\n"
        f"Supply: {supply} (dec={dec})\n"
        f"MCAP(est): {mcap}\n"
        f"Pair: {pair_addr}\n"
        f"PairCreatedAt(ms): {created_ms}\n"
    )
    print(txt)
    if push:
        await notify_serverchan(f"[MCAP TEST] {mint[:6]}...{mint[-4:]}", txt.replace("\n","\n\n"))
    await client.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mint", required=True)
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args()
    asyncio.run(main(args.mint, push=not args.no_push))