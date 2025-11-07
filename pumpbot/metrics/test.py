import asyncio
import aiohttp
import json

HELIUS_API_KEY = "YOUR_API_KEY_HERE"

# Example migration transaction from your screenshot
# Replace with an actual migration tx signature if you have one
EXAMPLE_MIGRATION_TX = "2kiARmLK1EHhPzD2i1creuCaWMbX5LTVFhtf3LZkLtpYTTD1Ad4UPbtCpL3HkwmcWvox8zkYNDwz4hFcoD6uPvD6"

async def fetch_transaction_details(signature):
    """Fetch and analyze a migration transaction"""
    url = f"https://mainnet.helius-rpc.com/?api-key=670abfb5-80f8-4732-8f77-9d96813e8198"
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            data = await response.json()
            
            if "result" in data and data["result"]:
                result = data["result"]
                print(f"🔍 Analyzing transaction: {signature}\n")
                
                # Check meta logs
                if "meta" in result and "logMessages" in result["meta"]:
                    logs = result["meta"]["logMessages"]
                    print(f"📋 LOGS ({len(logs)} total):")
                    for i, log in enumerate(logs):
                        print(f"   [{i}] {log}")
                    print()
                
                # Check instructions
                if "transaction" in result and "message" in result["transaction"]:
                    instructions = result["transaction"]["message"].get("instructions", [])
                    print(f"📝 INSTRUCTIONS ({len(instructions)} total):")
                    
                    for i, instr in enumerate(instructions):
                        print(f"\n   Instruction {i}:")
                        print(f"   Program: {instr.get('programId', 'N/A')}")
                        
                        # Parsed instruction
                        if "parsed" in instr:
                            parsed = instr["parsed"]
                            print(f"   Type: {parsed.get('type', 'N/A')}")
                            print(f"   Info: {json.dumps(parsed.get('info', {}), indent=6)}")
                        
                        # Raw instruction
                        else:
                            print(f"   Data: {instr.get('data', 'N/A')[:50]}...")
                            accounts = instr.get("accounts", [])
                            print(f"   Accounts: {len(accounts)}")
                            for acc in accounts[:3]:
                                print(f"      - {acc}")
                
                # Check inner instructions
                if "meta" in result and "innerInstructions" in result["meta"]:
                    inner = result["meta"]["innerInstructions"]
                    print(f"\n🔄 INNER INSTRUCTIONS ({len(inner)} groups):")
                    for group in inner:
                        print(f"   Index: {group.get('index')}")
                        for instr in group.get("instructions", [])[:3]:
                            if "parsed" in instr:
                                print(f"      - {instr['parsed'].get('type')}: {instr.get('program')}")
                
            else:
                print(f"❌ Transaction not found or error: {data}")

# Test with a known migration tx
asyncio.run(fetch_transaction_details(EXAMPLE_MIGRATION_TX))