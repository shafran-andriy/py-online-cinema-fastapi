import pytest

from database import get_db, MovieModel, GenreModel, DirectorModel, StarModel, CertificationModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload


@pytest.mark.anyio
async def test_update_movie_add_names(client):
    from main import app
    from security.deps import require_moderator
    app.dependency_overrides[require_moderator] = lambda: None

    async for db in get_db():
        cert = CertificationModel(name='UPD')
        g1 = GenreModel(name='G1')
        db.add_all([cert, g1])
        await db.flush()
        # create initial movie with g1
        movie = MovieModel(name='ToUpdate', year=2020, time=100, imdb=5.5, votes=10, description='u', price=1.0, certification_id=cert.id)
        db.add(movie)
        movie.genres = [g1]
        await db.commit()
        await db.refresh(movie)
        movie_id = movie.id
        break

    # now update: add new genre by name and director by name
    payload = {'genre_names': ['AddedG'], 'director_names': ['AddedDir']}
    resp = await client.patch(f'/api/v1/movies/{movie_id}/', json=payload)
    assert resp.status_code == 200

    async for db in get_db():
        stmt = select(MovieModel).options(joinedload(MovieModel.genres), joinedload(MovieModel.directors)).where(MovieModel.id == movie_id)
        res = await db.execute(stmt)
        movie = res.scalars().first()
        assert any(g.name == 'AddedG' for g in movie.genres)
        assert any(d.name == 'AddedDir' for d in movie.directors)
        break
