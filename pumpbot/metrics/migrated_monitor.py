import asyncio
import json
import websockets
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient

HELIUS_API_KEY = "670abfb5-80f8-4732-8f77-9d96813e8198"
BONDING_CURVE_PROGRAM = "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN"

# Initialize Async Solana RPC client
RPC_ENDPOINT = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

async def extract_token_mint(tx_sig, client):
    """Extract the newly created token mint from transaction with retry logic"""
    try:
        sig = Signature.from_string(str(tx_sig)) if isinstance(tx_sig, str) else tx_sig
        
        # Retry with exponential backoff (transaction needs time to be available)
        for attempt in range(8):
            await asyncio.sleep(1 * (attempt + 1))  # 1s, 2s, 3s, 4s, 5s, 6s, 7s, 8s
            
            try:
                tx = await client.get_transaction(
                    sig,
                    max_supported_transaction_version=0,
                    encoding="jsonParsed"
                )
                
                if tx.value:
                    mint_address = parse_token_mint(tx.value)
                    if mint_address:
                        print(f"   🪙 Token Mint: {mint_address}")
                        print(f"   🔗 DexScreener: https://dexscreener.com/solana/{mint_address}")
                        return mint_address
                    else:
                        print(f"   ⚠️  Could not extract token mint from transaction")
                        return None
            except Exception as e:
                if attempt < 7:  # Don't print error on last attempt
                    print(f"   ⏳ Attempt {attempt + 1}/8: Transaction not ready yet...")
                continue
        
        print(f"   ❌ Transaction not available after 8 retries")
        return None
        
    except Exception as e:
        print(f"   ❌ Error extracting mint: {e}")
        return None

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
            decimals = balance.ui_token_amount.decimals
            # Exclude wrapped SOL
            if mint != "So11111111111111111111111111111111111111112" and decimals == 6:
                # This is the newly created token!
                return mint
        
        return None
        
    except Exception as e:
        print(f"   ⚠️  Error parsing mint: {e}")
        return None

async def listen_for_migrations():
    url = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    
    # Create async client for RPC calls
    async with AsyncClient(RPC_ENDPOINT) as client:
        async with websockets.connect(url) as ws:
            subscription = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [BONDING_CURVE_PROGRAM]
                    },
                    {
                        "commitment": "confirmed"
                    }
                ]
            }

            await ws.send(json.dumps(subscription))
            first_response = await ws.recv()
            response = json.loads(first_response)
            
            if "result" in response:
                print(f"✅ Monitoring Meteora migrations...")
                print(f"⏰ Waiting for MigrationDammV2 instructions...\n")
            else:
                print(f"❌ Subscription failed: {response}")
                return

            while True:
                try:
                    message = await ws.recv()
                    data = json.loads(message)
                    
                    if "params" in data and "result" in data["params"]:
                        result = data["params"]["result"]["value"]
                        signature = result.get("signature")
                        logs = result.get("logs", [])
                        err = result.get("err")
                        
                        # Look for the migration instruction
                        is_migration = any("Program log: Instruction: MigrationDammV2" in log for log in logs)
                        
                        if is_migration and not err:
                            # Check if pool was created (this means migration is complete)
                            pool_created = any("create pool" in log.lower() for log in logs)
                            
                            if pool_created:
                                print(f"🚀 TOKEN MIGRATED!")
                                print(f"   📝 Tx: https://solscan.io/tx/{signature}")
                                print(f"   ✅ Pool created on Meteora DAMM v2")
                                
                                # Extract token mint address with retry logic
                                token_mint = await extract_token_mint(signature, client)
                                
                                if token_mint:
                                    print(f"   ✅ Token extracted successfully!")
                                
                                print()
                                
                except websockets.exceptions.ConnectionClosed:
                    print("⚠️  Connection closed. Reconnecting...")
                    await asyncio.sleep(5)
                    break
                except Exception as e:
                    print(f"❌ Error: {e}")
                    await asyncio.sleep(1)

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(listen_for_migrations())
        except KeyboardInterrupt:
            print("\n👋 Stopped monitoring")
            break
        except Exception as e:
            print(f"Connection error: {e}")
            print("Reconnecting in 5 seconds...")
            asyncio.sleep(5)