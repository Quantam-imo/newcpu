import asyncio

class EngineRunner:
    def __init__(self, engines):
        self.engines = engines

    async def run_engine(self, engine, market_data):
        return await engine.run(market_data)

    async def run_all(self, market_data):
        tasks = []
        for engine in self.engines:
            tasks.append(self.run_engine(engine, market_data))
        results = await asyncio.gather(*tasks)
        return results
