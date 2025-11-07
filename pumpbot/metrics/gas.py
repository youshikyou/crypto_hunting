# pumpbot/metrics/gas.py
import os, httpx
from decimal import Decimal
from typing import Optional, Sequence, Dict, Any

from pumpbot.config import BITQUERY_API_KEY, CONFIG

BITQUERY_ENDPOINT = "https://streaming.bitquery.io/eap"

# Bundler (tip) addresses. If you already define them elsewhere, you can import that instead.
DEFAULT_BUNDLERS: list[str] = CONFIG.get("BUNDLER_ADDRESSES") or [
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
]

# One query, three blocks (no time filters)
QUERY_TOTAL_FEES_NO_TIME = """
query ($addr: String!, $tips: [String!]!) {
  Solana {
    AllTransactionFees: Transactions(
      where: { Transaction: { Accounts: { includes: { Address: { is: $addr } } } } }
    ) {
      total_transaction_fees_SOL: sum(of: Transaction_Fee)
      total_transaction_fees_USD: sum(of: Transaction_FeeInUSD)
      transaction_count: count
    }

    DEXTradingFees: DEXTradeByTokens(
      where: { Trade: { Currency: { MintAddress: { is: $addr } } } }
    ) {
      trading_fees_SOL: sum(of: Transaction_Fee)
      trading_fees_USD: sum(of: Transaction_FeeInUSD)
      trade_count: count
    }

    BundleTippingFees: Transactions(
      where: {
        Transaction: {
          Accounts: {
            includes: [
              { Address: { is: $addr } },
              { Address: { in: $tips } }
            ]
          }
        }
      }
    ) {
      bundle_fees_SOL: sum(of: Transaction_Fee)
      bundle_fees_USD: sum(of: Transaction_FeeInUSD)
      bundle_count: count
    }
  }
}
"""

def _d(x) -> Decimal:
    try: return Decimal(str(x or "0"))
    except: return Decimal("0")

async def calc_total_fees_gmgn_style(
    client,                 # unused; kept for signature compatibility
    mint_address: str,      # <- only required parameter
    *,
    tip_addrs: Optional[Sequence[str]] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Returns:
    {
      'total_sol': float,               # AllTxn + DEX + Bundle (SOL)
      'parts': {
        'txn_sol': float,
        'dex_sol': float,
        'bundle_sol': float,
      },
      'counts': {
        'txn_count': int,
        'trade_count': int,
        'bundle_count': int,
      }
    }
    """
    token = token or BITQUERY_API_KEY or os.getenv("BITQUERY_API_KEY")
    if not token:
        print("BITQUERY_API_KEY not set")
        return {'total_sol': 0.0, 'parts': {'txn_sol': 0.0,'dex_sol': 0.0,'bundle_sol': 0.0}, 'counts': {'txn_count':0,'trade_count':0,'bundle_count':0}}

    tips = list(tip_addrs or DEFAULT_BUNDLERS)

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"query": QUERY_TOTAL_FEES_NO_TIME, "variables": {"addr": mint_address, "tips": tips}}

    async with httpx.AsyncClient(timeout=45) as s:
        r = await s.post(BITQUERY_ENDPOINT, json=payload, headers=headers)
        if r.status_code != 200:
            print(f"[Bitquery] HTTP {r.status_code}: {r.text[:400]}")
            return {'total_sol': 0.0, 'parts': {'txn_sol': 0.0,'dex_sol': 0.0,'bundle_sol': 0.0}, 'counts': {'txn_count':0,'trade_count':0,'bundle_count':0}}
        j = r.json()
        if "errors" in j:
            print(f"[Bitquery] errors: {j['errors']}")
            return {'total_sol': 0.0, 'parts': {'txn_sol': 0.0,'dex_sol': 0.0,'bundle_sol': 0.0}, 'counts': {'txn_count':0,'trade_count':0,'bundle_count':0}}

    sol = (j.get("data") or {}).get("Solana") or {}

    txn = (sol.get("AllTransactionFees") or [{}])[0]
    dex = (sol.get("DEXTradingFees") or [{}])[0]
    bun = (sol.get("BundleTippingFees") or [{}])[0]

    txn_sol = float(_d(txn.get("total_transaction_fees_SOL")))
    dex_sol = float(_d(dex.get("trading_fees_SOL")))
    bun_sol = float(_d(bun.get("bundle_fees_SOL")))

    return {
        'total_sol': txn_sol + dex_sol + bun_sol,
        'parts': {
            'txn_sol': txn_sol,
            'dex_sol': dex_sol,
            'bundle_sol': bun_sol,
        },
        'counts': {
            'txn_count': int(txn.get("transaction_count") or 0),
            'trade_count': int(dex.get("trade_count") or 0),
            'bundle_count': int(bun.get("bundle_count") or 0),
        }
    }
