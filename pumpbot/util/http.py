import httpx
from pumpbot.config import CONFIG


async def http_get(url: str, headers: dict | None = None, timeout: int = CONFIG["HTTP_TIMEOUT"]):
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as s:
        return await s.get(url)


async def http_post(url: str, data: dict, headers: dict | None = None, timeout: int = CONFIG["HTTP_TIMEOUT"]):
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as s:
        return await s.post(url, data=data)