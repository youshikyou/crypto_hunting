"""
Simple PumpPortal Migration Listener
Listen for meme coins migrating from bonding curves
"""

import asyncio
import websockets
import json

async def subscribe():
    uri = "wss://pumpportal.fun/api/data"
    async with websockets.connect(uri) as websocket:
        # Subscribing to migration events
        payload = {
            "method": "subscribeMigration",
        }
        await websocket.send(json.dumps(payload))
        async for message in websocket:
            print(json.loads(message))

# Run it
# Run the subscribe function
asyncio.get_event_loop().run_until_complete(subscribe())