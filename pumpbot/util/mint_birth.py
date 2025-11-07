import asyncio
from solders.pubkey import Pubkey
from pumpbot.chain.rpc import get_client

# 返回 mint 首次出现的区块时间（毫秒）
async def get_mint_creation_ms(mint: str) -> int | None:
    client = await get_client()
    before = None
    oldest_ms = None
    while True:
        # 注意：大多数 RPC 限制 limit<=1000
        resp = await client.get_signatures_for_address(Pubkey.from_string(mint), before=before, limit=1000)
        sigs = resp.value or []
        if not sigs:
            break
        # 接口通常是“新到旧”排序；这一页最后一个是当前页里最老的
        last = sigs[-1]
        if last.block_time is not None:
            oldest_ms = int(last.block_time) * 1000
        # 翻到更老的一页
        before = last.signature
        if len(sigs) < 1000:
            break
    return oldest_ms