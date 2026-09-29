import os
import sys

# The suites live in tests/ but read fixtures from, and import, the repo root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import asyncio
from shared.pdf_extractor import parse_delta_dental_pdf

async def test():
    print("Testing PDF extractor...")
    # Empty PDF content essentially
    try:
        res = await parse_delta_dental_pdf(b"test pdf")
        print(res)
    except Exception as e:
        print(f"Exception: {e}")

asyncio.run(test())
