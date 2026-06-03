import os
import asyncio
import pytest

os.environ['ENVIRONMENT'] = 'testing'

import anyio
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from config import get_settings
from database.session_sqlite import reset_sqlite_database
from database import UserGroupModel, get_db
from main import app


class DummyEmailSender:
    def __init__(self):
        self.sent = []

    async def send_activation_email(self, email, link):
        self.sent.append(('activation', email, link))

    async def send_activation_complete_email(self, email, link):
        self.sent.append(('activation_complete', email, link))

    async def send_password_reset_email(self, email, link):
        self.sent.append(('password_reset', email, link))

    async def send_password_reset_complete_email(self, email, link):
        self.sent.append(('password_reset_complete', email, link))


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'


@pytest.fixture(autouse=True)
def prepare_db():
    # Reset DB schema and seed default user groups synchronously for pytest
    asyncio.run(reset_sqlite_database())

    async def _seed():
        async for db in get_db():
            db.add(UserGroupModel(name='user'))
            db.add(UserGroupModel(name='moderator'))
            db.add(UserGroupModel(name='admin'))
            await db.commit()
            break

    asyncio.run(_seed())


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as ac:
        # override email sender dependency
        dummy = DummyEmailSender()
        app.dependency_overrides[get_settings] = lambda: get_settings()
        from config.dependencies import get_accounts_email_notificator
        app.dependency_overrides[get_accounts_email_notificator] = lambda: dummy
        yield ac
        app.dependency_overrides.clear()
