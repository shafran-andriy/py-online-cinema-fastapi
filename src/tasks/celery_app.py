import os
import asyncio
from celery import Celery

from services.accounts import delete_expired_activation_tokens
from database.session_sqlite import AsyncSessionLocal

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

app = Celery('py_online_cinema_tasks', broker=REDIS_URL)
app.conf.beat_schedule = {
    'delete-expired-activation-tokens-every-day': {
        'task': 'tasks.delete_expired_activation_tokens_task',
        'schedule': 60 * 60 * 24,  # once a day
    }
}
app.conf.timezone = 'UTC'


@app.task(name='tasks.delete_expired_activation_tokens_task')
def delete_expired_activation_tokens_task():
    """Celery task wrapper that runs the async deletion function in the event loop."""
    async def _run():
        async with AsyncSessionLocal() as db:
            await delete_expired_activation_tokens(db)

    # run the coroutine
    try:
        asyncio.run(_run())
    except Exception as e:
        # Celery will mark the task as failed; log exception to stdout
        print('Error running delete_expired_activation_tokens_task:', e)
        raise
