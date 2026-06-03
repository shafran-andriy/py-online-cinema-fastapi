import asyncio
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from database.session_sqlite import reset_sqlite_database
from database import get_db, CertificationModel
from main import app

async def main():
    await reset_sqlite_database()
    async for db in get_db():
        cert = CertificationModel(name='R')
        db.add(cert)
        await db.flush()
        movie_payload = {
            'name': 'CRUD Movie',
            'year': 2021,
            'time': 100,
            'imdb': 8.1,
            'votes': 500,
            'description': 'CRUD test',
            'price': 12.50,
            'certification_id': cert.id,
        }
        await db.commit()
        break

    # bypass moderator dependency like tests do
    from security.deps import require_moderator
    app.dependency_overrides[require_moderator] = lambda: None

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as ac:
        resp = await ac.post('/api/v1/theater/movies/', json=movie_payload)
        print('STATUS', resp.status_code)
        try:
            print('JSON', resp.json())
        except Exception:
            print('TEXT', resp.text)

asyncio.run(main())
