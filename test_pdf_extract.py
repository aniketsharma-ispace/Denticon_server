import asyncio
from pdf_extractor import parse_delta_dental_pdf

async def test():
    print("Testing PDF extractor...")
    # Empty PDF content essentially
    try:
        res = await parse_delta_dental_pdf(b"test pdf")
        print(res)
    except Exception as e:
        print(f"Exception: {e}")

asyncio.run(test())
