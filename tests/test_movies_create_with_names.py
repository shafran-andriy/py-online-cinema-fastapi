import pytest

from database import get_db, MovieModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload


@pytest.mark.anyio
async def test_create_movie_with_names(client):
    from main import app
    from security.deps import require_moderator
    app.dependency_overrides[require_moderator] = lambda: None

    async for db in get_db():
        # create a certification for this test
        from database import CertificationModel
        cert = CertificationModel(name='CN')
        db.add(cert)
        await db.flush()
        await db.commit()
        movie_payload = {
            'name': 'Name Movie',
            'year': 2023,
            'time': 125,
            'imdb': 7.5,
            'votes': 300,
            'description': 'Created by names',
            'price': 9.99,
            'certification_id': cert.id,
            'genre_names': ['NewGenreA', 'NewGenreB'],
            'director_names': ['NewDirector'],
            'star_names': ['NewStar'],
        }
        break

    resp = await client.post('/api/v1/movies/', json=movie_payload)
    assert resp.status_code == 201
    data = resp.json()
    movie_id = data['id']

    async for db in get_db():
        stmt = select(MovieModel).options(
            joinedload(MovieModel.genres),
            joinedload(MovieModel.directors),
            joinedload(MovieModel.stars),
        ).where(MovieModel.id == movie_id)
        res = await db.execute(stmt)
        movie = res.scalars().first()
        assert movie is not None
        assert any(g.name == 'NewGenreA' for g in movie.genres)
        assert any(g.name == 'NewGenreB' for g in movie.genres)
        assert any(d.name == 'NewDirector' for d in movie.directors)
        assert any(s.name == 'NewStar' for s in movie.stars)
        break
