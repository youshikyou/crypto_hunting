import asyncio, json
from pumpbot.dex.dexscreener import retry_get_pair

async def main(mint: str):
    pair = await retry_get_pair(mint)
    print(json.dumps(pair or {}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mint", required=True)
    args = p.parse_args()
    asyncio.run(main(args.mint))
