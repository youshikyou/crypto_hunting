import httpx
from solana.rpc.async_api import AsyncClient
from pumpbot.config import RPC_URL, CONFIG


def get_client() -> AsyncClient:
    return AsyncClient(RPC_URL, commitment="confirmed")


aSYNC_HEADERS = {"Content-Type": "application/json"}


async def rpc_call(method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=CONFIG["HTTP_TIMEOUT"]) as s:
        r = await s.post(RPC_URL, headers=aSYNC_HEADERS, json=payload)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    
    return data["result"]