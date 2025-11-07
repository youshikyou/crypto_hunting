import asyncio
from pumpbot.chain.rpc import get_client
from pumpbot.util.notify import notify_serverchan
from pumpbot.metrics.holders import compute_top_ratio

async def main(mint: str, push: bool = True):
    client = get_client()
    try:
        ratio = await compute_top_ratio(client, mint)  # returns 0..1 or None
        pct = None if ratio is None else round(ratio * 100, 2)
        txt = f"Mint: {mint}\nTop10 Holder Ratio: {pct}%"
        print(txt)
        if push:
            await notify_serverchan(f"[HOLDERS TEST] {mint[:6]}...{mint[-4:]}", txt.replace('\n', '\n\n'))
    finally:
        await client.close()

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mint", required=True)
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args()
    asyncio.run(main(args.mint, push=not args.no_push))
