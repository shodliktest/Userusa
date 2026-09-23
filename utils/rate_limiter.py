import asyncio, time
from collections import defaultdict

class RateLimiter:
    def __init__(self,min_interval=0.8):
        self.min_interval=min_interval
        self.last=defaultdict(float)
        self.lock=asyncio.Lock()

    async def wait(self,key="global"):
        async with self.lock:
            now=time.monotonic()
            delay=self.min_interval-(now-self.last[key])
            if delay>0:
                await asyncio.sleep(delay)
            self.last[key]=time.monotonic()
