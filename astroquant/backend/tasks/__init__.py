# Task system for AstroQuant using Celery
from celery import Celery

celery_app = Celery(
    'astroquant',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

@celery_app.task
def run_engine_task(engine_name, *args, **kwargs):
    # Dynamically import and run engine
    module = __import__(f"astroquant.engine.{engine_name}", fromlist=[engine_name])
    engine_class = getattr(module, engine_name)
    engine = engine_class()
    return engine.run(*args, **kwargs)
