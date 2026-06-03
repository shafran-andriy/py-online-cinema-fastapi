import pytest
from uuid import uuid4

from database import get_db, MovieModel, CertificationModel, GenreModel


@pytest.mark.anyio
async def test_list_movies(client):
    # seed a movie
    async for db in get_db():
        cert = CertificationModel(name='PG-13')
        db.add(cert)
        await db.flush()
        movie = MovieModel(
            uuid=str(uuid4()),
            name='Test Movie',
            year=2020,
            time=120,
            imdb=7.5,
            votes=1000,
            description='A test movie',
            price=9.99,
            certification_id=cert.id,
        )
        db.add(movie)
        await db.commit()
        break

    resp = await client.get('/api/v1/theater/movies/')
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(m['name'] == 'Test Movie' for m in data)
