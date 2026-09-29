import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as c:
        try:
            print("Sending request...")
            res = await c.post('http://127.0.0.1:11434/api/generate', json={'model': 'qwen2.5:latest', 'prompt': 'test'})
            print(f"Status Code: {res.status_code}")
            print(f"Text: {res.text}")
        except Exception as e:
            print(f"Exception: {e}")

asyncio.run(test())
