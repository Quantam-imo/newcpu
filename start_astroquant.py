import asyncio
from orchestrator.signal_orchestrator import SignalOrchestrator

orchestrator = SignalOrchestrator()

asyncio.run(orchestrator.run())
