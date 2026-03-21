import os
import importlib
import asyncio

class EngineManager:
    def __init__(self, engine_folder="astroquant.engine"):
        self.engine_folder = engine_folder
        self.engines = []

    def load_engines(self):
        folder_path = self.engine_folder.replace('.', os.sep)
        for file in os.listdir(folder_path):
            if file.endswith("_engine.py"):
                module_name = file.replace(".py", "")
                module_path = f"{self.engine_folder}.{module_name}"
                module = importlib.import_module(module_path)
                for attr in dir(module):
                    obj = getattr(module, attr)
                    if isinstance(obj, type):
                        try:
                            instance = obj()
                            self.engines.append(instance)
                        except Exception:
                            pass
        print(f"{len(self.engines)} engines loaded")

    async def run_engines(self, market_data):
        tasks = []
        for engine in self.engines:
            tasks.append(engine.run(market_data))
        results = await asyncio.gather(*tasks)
        return results
