import pytest
from uuid import uuid4

from database import get_db, MovieModel, CertificationModel, GenreModel, DirectorModel, StarModel


@pytest.mark.anyio
async def test_movie_relations_create(client):
    # Override moderator requirement
    from main import app
    from security.deps import require_moderator
    app.dependency_overrides[require_moderator] = lambda: None

    async for db in get_db():
        cert = CertificationModel(name='PG')
        g1 = GenreModel(name='Action')
        g2 = GenreModel(name='Drama')
        d1 = DirectorModel(name='Dir One')
        s1 = StarModel(name='Star One')
        db.add_all([cert, g1, g2, d1, s1])
        await db.flush()
        genre_ids = [g1.id, g2.id]
        director_ids = [d1.id]
        star_ids = [s1.id]
        movie_payload = {
            'name': 'Rel Movie',
            'year': 2022,
            'time': 110,
            'imdb': 7.0,
            'votes': 200,
            'description': 'Rel test',
            'price': 5.00,
            'certification_id': cert.id,
            'genre_ids': genre_ids,
            'director_ids': director_ids,
            'star_ids': star_ids,
        }
        await db.commit()
        break

    resp = await client.post('/api/v1/theater/movies/', json=movie_payload)
    assert resp.status_code == 201
    data = resp.json()
    movie_id = data['id']

    # verify relations in DB
    async for db in get_db():
        movie = await db.get(MovieModel, movie_id)
        assert movie is not None
        assert len(movie.genres) == 2
        assert len(movie.directors) == 1
        assert len(movie.stars) == 1
        break
