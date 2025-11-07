from solana.rpc.websocket_api import connect
from solana.rpc.async_api import AsyncClient
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


client = AsyncClient(RPC_URL)

async def monitor_token_creation():
    async for websocket in connect(WSS_URL):
        print(" Connected to Helius WebSocket.")
        program_pubkey = Pubkey.from_string(DBC_PROGRAM_ID)
        filter_mentions = RpcTransactionLogsFilterMentions(program_pubkey)
        await websocket.logs_subscribe(filter_mentions,commitment=Commitment("confirmed"))

        async for msgs in websocket:
            try:
                for msg in msgs:
                    if hasattr(msg, 'result') and msg.result:
                        value = msg.result.value
                        tx_sig = str(value.signature)
                        logs = value.logs
                        logs_text = "\n".join(logs) 
                        if "Instruction: InitializeVirtualPoolWithSplToken" in logs_text:
                            # print(f"Solscan: https://solscan.io/tx/{tx_sig}")
                            asyncio.create_task(extract_token_mint(tx_sig))
            except Exception as e:
                print(f"Error processing message: {e}")

async def extract_token_mint(tx_sig):
    """Extract the newly created token mint from transaction"""
    try:
        sig = Signature.from_string(str(tx_sig)) if isinstance(tx_sig, str) else tx_sig
        
        # Retry with backoff
        for attempt in range(8):
            await asyncio.sleep(1 * (attempt + 1))
            
            tx = await client.get_transaction(
                sig,
                max_supported_transaction_version=0,
                encoding="jsonParsed"
            )
            if tx.value:
                mint_address = parse_token_mint(tx.value)
                if mint_address:
                    print(f"Solscan: https://solscan.io/tx/{tx_sig}")
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
            mint = str(balance.mint)
            # Exclude wrapped SOL
            if mint != "So11111111111111111111111111111111111111112":
                # This is the newly created token!
                return mint
        
        return None
        
    except Exception as e:
        print(f"   Error parsing mint: {e}")
        return None

if __name__ == "__main__":
    asyncio.run(monitor_token_creation())
