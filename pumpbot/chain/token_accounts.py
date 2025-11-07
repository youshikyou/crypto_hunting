import base64
from typing import Dict, List, Optional
from solders.pubkey import Pubkey
from pumpbot.config import (
    SYSTEM_PROGRAM_ID,
    TOKEN_PROGRAM_ID_V1,
    INCINERATOR,
)
from pumpbot.chain.rpc import rpc_call


async def get_token_accounts_by_mint_all(mint: str, program_id: str,after: Optional[str] = None) -> List[dict]:
    # Token-2022账户长度不固定，不强制 dataSize 过滤
    filters = [{"memcmp": {"offset": 0, "bytes": mint}}]
    if program_id == TOKEN_PROGRAM_ID_V1:
        filters.insert(0, {"dataSize": 165})
    params = [program_id, {"encoding": "base64", "filters": filters}]
    if after:
        params[1]["after"] = after
    return await rpc_call("getProgramAccounts", params)


async def get_multiple_accounts(pubkeys: list[str]) -> dict:
    params = [pubkeys, {"encoding": "base64"}]
    return await rpc_call("getMultipleAccounts", params)


async def aggregate_owner_balances(items: List[dict]) -> Dict[str, int]:
    by_owner: Dict[str, int] = {}
    for it in items:
        acc = it.get("account", {})
        data_b64 = (acc.get("data") or [None])[0]
        if not data_b64:
            continue
        data = base64.b64decode(data_b64)
        if len(data) < 72:
            continue
        owner = str(Pubkey(data[32:64]))
        amount_raw = int.from_bytes(data[64:72], "little")
        if amount_raw <= 0:
            continue
        if owner == INCINERATOR:
            continue
        by_owner[owner] = by_owner.get(owner, 0) + amount_raw
    return by_owner


async def filter_system_owners(candidates: list[str]) -> List[str]:
    keep: set[str] = set()
    multi = await get_multiple_accounts(candidates)
    for i, acc in enumerate(multi.get("value") or []):
        if not acc:
            continue
        if acc.get("owner") == SYSTEM_PROGRAM_ID and not acc.get("executable", False):
            keep.add(candidates[i])
    return [o for o in candidates if o in keep]

async def filter_user_wallets(candidates: List[str]) -> List[str]:
    """
    只保留“像个人钱包”的地址：
      - owner == System Program
      - executable == False
      - 公钥在曲线上（is_on_curve == True）
      - 不在已知黑名单
    """
    keep: List[str] = []
    resp = await get_multiple_accounts(candidates)
    print(resp)
    values = resp.get("value") or []

    for i, acc in enumerate(values):
        if not acc:
            continue
        owner = acc.get("owner")
        if owner != SYSTEM_PROGRAM_ID:
            continue
        if acc.get("executable", False):
            continue

        addr = candidates[i]

        try:
            if Pubkey.from_string(addr).is_on_curve():
                keep.append(addr)
        except Exception:
            continue

        # if addr in KNOWN_NON_USER_WALLETS:
        #     continue

    return keep