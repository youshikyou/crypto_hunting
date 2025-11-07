from solana.rpc.websocket_api import connect
from solana.rpc.api import Client
from solana.rpc.commitment import Commitment
from solders.pubkey import Pubkey
from solders.rpc.config import RpcTransactionLogsFilterMentions
from solders.signature import Signature
import asyncio
import time
# --- CONFIG ---
RPC_URL = "https://mainnet.helius-rpc.com/?api-key=670abfb5-80f8-4732-8f77-9d96813e8198"
WSS_URL = RPC_URL.replace("https", "wss")
DBC_PROGRAM_ID = "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN"  # Meteora DBC

client = Client(RPC_URL)


# def process_transaction(tx_sig):
#     try:
#         if isinstance(tx_sig, str):
#             sig = Signature.from_string(tx_sig)
#         else:
#             sig = tx_sig
        
#         tx = client.get_transaction(
#             sig,
#             max_supported_transaction_version=0,
#             encoding="jsonParsed"
#         )
#         if not tx.value:
#             print(f"No transaction data for {tx_sig}")
#             return
        
#         print(tx)
#         meta = tx.value.transaction.meta
#         if meta and meta.log_messages:
#             logs = "\n".join(meta.log_messages)
#             if "initialize_virtual_pool_with_spl_token" in logs:
#                 print(f"New pool creation detected in TX: {tx_sig}")
#                 print(f"View on Solscan: https://solscan.io/tx/{tx_sig}")
#     except Exception as e:
#         print(f"Error processing transaction {tx_sig}: {e}")


def extract_token_mint(tx_sig):
    """Extract the newly created token mint from transaction"""
    try:
        sig = Signature.from_string(str(tx_sig)) if isinstance(tx_sig, str) else tx_sig
        
            
        tx = client.get_transaction(
            sig,
            max_supported_transaction_version=0,
            encoding="jsonParsed"
        )
        
        if tx.value:
            mint_address = parse_token_mint(tx.value)
            if mint_address:
                print(f"Token Mint: {mint_address}")
            else:
                print(f"Could not extract token mint")
            print()
            return
        
        print(f"Transaction not available after retries\n")
        
    except Exception as e:
        print(f"Error: {e}\n")

def parse_token_mint(tx_value):
    """
    Parse the token mint from the transaction.
    The new token mint appears in post_token_balances.
    """
    try:
        meta = tx_value.transaction.meta
        
        if not meta or not hasattr(meta, 'post_token_balances'):
            return None
        
        if not meta.post_token_balances:
            return None
        
        # Find the token mint that is NOT wrapped SOL
        for balance in meta.post_token_balances:
            mint = balance.mint
            decimals = balance.ui_token_amount.decimals
            # Exclude wrapped SOL
            if mint != "So11111111111111111111111111111111111111112" and decimals == 6:
                # This is the newly created token!
                return mint
        
        return None
        
    except Exception as e:
        print(f"   Error parsing mint: {e}")
        return None


if __name__ == "__main__":
    extract_token_mint(tx_sig='3NT5TfmBMSpw8RWctHic1hCW5TV2fuXgz2zhnBYdJhZWKu39rsiE9GnVTgdvtq5n68HDp5WU3PyyWovVnebkNPm8')
