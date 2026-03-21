from celery import Celery

import os
broker_url = os.environ.get("REDIS_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/0")
celery_app = Celery(
    "astroquant",
    broker=broker_url,
    backend=backend_url
)

# Example task for engine execution
def run_engine(engine_name, *args, **kwargs):
    module = __import__(f"astroquant.engine.{engine_name}", fromlist=[engine_name])
    engine_class = getattr(module, engine_name)
    engine = engine_class()
    return engine.run(*args, **kwargs)

celery_app.task(run_engine)
