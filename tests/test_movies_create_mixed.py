import pytest

from database import get_db, MovieModel, GenreModel, DirectorModel, StarModel, CertificationModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload


@pytest.mark.anyio
async def test_create_movie_mixed(client):
    from main import app
    from security.deps import require_moderator
    app.dependency_overrides[require_moderator] = lambda: None

    async for db in get_db():
        # create existing genre and star
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

    resp = await client.post('/api/v1/theater/movies/', json=movie_payload)
    assert resp.status_code == 201
    data = resp.json()
    movie_id = data['id']

    async for db in get_db():
        stmt = select(MovieModel).options(
            joinedload(MovieModel.genres), joinedload(MovieModel.directors), joinedload(MovieModel.stars)
        ).where(MovieModel.id == movie_id)
        res = await db.execute(stmt)
        movie = res.scalars().first()
        assert movie is not None
        assert any(g.name == 'ExistG' for g in movie.genres)
        assert any(g.name == 'NewG1' for g in movie.genres)
        assert any(d.name == 'NewDirA' for d in movie.directors)
        assert any(s.name == 'ExistS' for s in movie.stars)
        assert any(s.name == 'NewStarA' for s in movie.stars)
        break
