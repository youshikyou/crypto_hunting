import os
import asyncio
import argparse
from pumpbot.watchers.migrated import listen_migrated


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Listen PumpPortal migrations")
    p.add_argument("--minutes", type=int, default=int(os.getenv("PB_LISTEN_MINUTES", 10)),
                   help="监听分钟数；<=0 表示不限制")
    p.add_argument("--max-items", type=int, default=int(os.getenv("PB_LISTEN_MAX_ITEMS", 20)),
                   help="最多抓取条数；<=0 表示不限制")
    p.add_argument("--no-push", action="store_true", help="仅打印，不推送 Server酱")
    args = p.parse_args()

    minutes = None if args.minutes <= 0 else args.minutes
    max_items = None if args.max_items <= 0 else args.max_items
    asyncio.run(listen_migrated(minutes=minutes, max_items=max_items, push=not args.no_push))
