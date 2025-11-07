from pumpbot.config import SERVERCHAN_KEY
from pumpbot.util.http import http_post


async def notify_serverchan(title: str, content_md: str):
    if not SERVERCHAN_KEY:
        print("[WARN] SERVERCHAN_KEY not set; skip push")
        return
    
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    
    data = {"title": title, "desp": content_md}
    try:
        r = await http_post(url, data)
        print("Server酱响应:", r.status_code, r.text[:200])
    except Exception as e:
        print("Server酱推送失败:", e)