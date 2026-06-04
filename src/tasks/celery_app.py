import os
import asyncio
from celery import Celery

from tasks.cleanup import (
    cleanup_expired_activation_tokens,
    cleanup_expired_password_reset_tokens,
    cleanup_expired_refresh_tokens,
)
from database.session_sqlite import AsyncSessionLocal

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

app = Celery('py_online_cinema_tasks', broker=REDIS_URL)
app.conf.beat_schedule = {
    'delete-expired-activation-tokens-every-day': {
        'task': 'tasks.delete_expired_activation_tokens_task',
        'schedule': 60 * 60 * 24,
    },
    'delete-expired-password-reset-tokens-every-day': {
        'task': 'tasks.delete_expired_password_reset_tokens_task',
        'schedule': 60 * 60 * 24,
    },
    'delete-expired-refresh-tokens-every-day': {
        'task': 'tasks.delete_expired_refresh_tokens_task',
        'schedule': 60 * 60 * 24,
    },
}
app.conf.timezone = 'UTC'


def _run_async(coro):
    try:
        asyncio.run(coro)
    except Exception as e:
        print(f'Celery task error: {e}')
        raise


@app.task(name='tasks.delete_expired_activation_tokens_task')
def delete_expired_activation_tokens_task():
    async def _run():
        async with AsyncSessionLocal() as db:
            await cleanup_expired_activation_tokens(db)
    _run_async(_run())


@app.task(name='tasks.delete_expired_password_reset_tokens_task')
def delete_expired_password_reset_tokens_task():
    async def _run():
        async with AsyncSessionLocal() as db:
            await cleanup_expired_password_reset_tokens(db)
    _run_async(_run())


@app.task(name='tasks.delete_expired_refresh_tokens_task')
def delete_expired_refresh_tokens_task():
    async def _run():
        async with AsyncSessionLocal() as db:
            await cleanup_expired_refresh_tokens(db)
    _run_async(_run())
