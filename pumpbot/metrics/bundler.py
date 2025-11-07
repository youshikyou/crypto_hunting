import os, httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Set

from pumpbot.config import BITQUERY_API_KEY

BITQUERY_ENDPOINT = "https://streaming.bitquery.io/eap"

# Pull BOTH DEX buys and SPL transfers for the mint (EAP ~last 8h)
QUERY_EAP = """
query ($token: String!) {
  Solana {
    trades: DEXTradeByTokens(
      where: {
        Transaction: { Result: { Success: true } }
        Trade: {
          Currency: { MintAddress: { is: $token } }
          Side: { Type: { is: buy } }
        }
      }
      orderBy: { ascending: Block_Slot }
      limit: { count: 100000 }
    ) {
      Block { Slot Time }
      Transaction { Signer Signature }
    }
    transfers: Transfers(
      where: {
        Transaction: { Result: { Success: true } }
        Transfer: { Currency: { MintAddress: { is: $token } } }
      }
      orderBy: { ascending: Block_Slot }
      limit: { count: 100000 }
    ) {
      Block { Slot Time }
      Transaction { Signer Signature }
    }
  }
}
"""

def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _slot_to_int(v) -> int | None:
    try:
        return int(str(v))
    except Exception:
        return None

async def calc_bundlers_ratio_eap(token_mint: str) -> Dict[str, Any]:
    """
    Axiom-style Bundlers Ratio over EAP (~last 8h), no options:
      - Bundled slot: >= 4 distinct signers in same slot (trades + transfers).
      - Pattern filter: if a wallet appears in a bundled slot but its NEXT tx is unbundled, drop it.
      - Ratio = (# bundler wallets) / (# all wallets that transacted for this mint).
    """
    api_key = BITQUERY_API_KEY
    if not api_key:
        return {"ok": False, "error": "BITQUERY_API_KEY not set", "token_mint": token_mint}

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {"query": QUERY_EAP, "variables": {"token": token_mint}}

    async with httpx.AsyncClient(timeout=45) as s:
        r = await s.post(BITQUERY_ENDPOINT, json=payload, headers=headers)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}", "token_mint": token_mint}
        j = r.json()
        if "errors" in j:
            return {"ok": False, "error": str(j["errors"])[:300], "token_mint": token_mint}

    sol = (j.get("data") or {}).get("Solana") or {}
    trades = sol.get("trades") or []
    transfers = sol.get("transfers") or []

    # unify events: (slot, signer, sig)
    events: List[Dict[str, Any]] = []
    for it in trades:
        slot = _slot_to_int((it.get("Block") or {}).get("Slot"))
        tx = it.get("Transaction") or {}
        signer = tx.get("Signer")
        sig = tx.get("Signature") or ""
        if slot is not None and isinstance(signer, str):
            events.append({"slot": slot, "signer": signer, "sig": sig})
    for it in transfers:
        slot = _slot_to_int((it.get("Block") or {}).get("Slot"))
        tx = it.get("Transaction") or {}
        signer = tx.get("Signer")
        sig = tx.get("Signature") or ""
        if slot is not None and isinstance(signer, str):
            events.append({"slot": slot, "signer": signer, "sig": sig})

    if not events:
        t_end = datetime.now(timezone.utc); t_start = t_end - timedelta(hours=8)
        return {
            "ok": True, "token_mint": token_mint, "window_start": _iso(t_start), "window_end": _iso(t_end),
            "total_wallets": 0, "bundler_wallets": 0, "bundled_slots": 0,
            "bundlers_ratio": 0.0, "bundlers_ratio_pct": "0.00%"
        }

    # overall wallet set + per-slot signer sets
    all_wallets: Set[str] = {e["signer"] for e in events}
    by_slot: Dict[int, Set[str]] = {}
    for e in events:
        by_slot.setdefault(e["slot"], set()).add(e["signer"])

    # Axiom threshold: >= 4 signers in same slot
    print(len(by_slot.keys()))
    bundled_slots = [s for s, signers in by_slot.items() if len(signers) >= 4]
    bundled_set = set(bundled_slots)

    # candidate bundlers = union of signers in bundled slots
    candidates: Set[str] = set()
    for s in bundled_slots:
        candidates |= by_slot[s]

    # Axiom pattern filter: drop wallets if their NEXT tx is unbundled
    filtered: Set[str] = set()
    if candidates:
        by_signer: Dict[str, List[Dict[str, Any]]] = {}
        for e in events:
            if e["signer"] in candidates:
                by_signer.setdefault(e["signer"], []).append(e)
        for signer, lst in by_signer.items():
            lst.sort(key=lambda x: (x["slot"], x["sig"]))
            bundled_idxs = [i for i, ev in enumerate(lst) if ev["slot"] in bundled_set]
            if not bundled_idxs:
                continue
            drop = any((i + 1 < len(lst) and lst[i + 1]["slot"] not in bundled_set) for i in bundled_idxs)
            if not drop:
                filtered.add(signer)

    t_end = datetime.now(timezone.utc); t_start = t_end - timedelta(hours=8)
    total = len(all_wallets)
    bundlers = len(filtered)
    ratio = (bundlers / total) if total else 0.0

    return {
        "ok": True,
        "token_mint": token_mint,
        "window_start": _iso(t_start),
        "window_end": _iso(t_end),
        "total_wallets": total,
        "bundler_wallets": bundlers,
        "bundled_slots": len(bundled_slots),
        "bundlers_ratio": ratio,
        "bundlers_ratio_pct": f"{ratio * 100:.2f}%"
    }