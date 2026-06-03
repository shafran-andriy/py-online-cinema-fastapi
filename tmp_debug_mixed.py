import asyncio
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from database.session_sqlite import reset_sqlite_database
from database import get_db, CertificationModel, GenreModel, StarModel
from main import app

async def main():
    await reset_sqlite_database()
    async for db in get_db():
        cert = CertificationModel(name='MIX')
        g_existing = GenreModel(name='ExistG')
        s_existing = StarModel(name='ExistS')
        db.add_all([cert, g_existing, s_existing])
        await db.flush()
        await db.commit()
        movie_payload = {
            'name': 'Mixed Movie',
            'year': 2024,
            'time': 90,
            'imdb': 6.5,
            'votes': 120,
            'description': 'Mixed ids and names',
            'price': 4.99,
            'certification_id': cert.id,
            'genre_ids': [g_existing.id],
            'genre_names': ['NewG1'],
            'director_names': ['NewDirA'],
            'star_ids': [s_existing.id],
            'star_names': ['NewStarA']
        }
        break

    # override moderator
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
