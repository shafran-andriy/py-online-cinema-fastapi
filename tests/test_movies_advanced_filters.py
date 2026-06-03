import pytest
from database import GenreModel, MovieModel, CertificationModel, DirectorModel, StarModel
from database import get_db
from sqlalchemy import select


@pytest.mark.anyio
async def test_advanced_filters_and_edgecases(client):
    async for db in get_db():
        cert = CertificationModel(name='ADV')
        g = GenreModel(name='GF')
        d = DirectorModel(name='DirX')
        s = StarModel(name='StarX')
        db.add_all([cert, g, d, s])
        await db.flush()
        m1 = MovieModel(name='FilterA', year=2019, time=100, imdb=7.2, votes=10, description='abc', price=1.5, certification_id=cert.id)
        m2 = MovieModel(name='FilterB', year=2020, time=120, imdb=8.1, votes=20, description='def', price=5.0, certification_id=cert.id)
        db.add_all([m1, m2])
        await db.flush()
        from database.models.movies import movie_genres, movie_directors, movie_stars
        await db.execute(movie_genres.insert().values(movie_id=m1.id, genre_id=g.id))
        await db.execute(movie_directors.insert().values(movie_id=m1.id, director_id=d.id))
        await db.execute(movie_stars.insert().values(movie_id=m1.id, star_id=s.id))
        await db.commit()
        break

    # filter by director_name
    resp = await client.get('/api/v1/theater/movies/?director_name=DirX')
    assert resp.status_code == 200
    data = resp.json()
    assert data['total'] >= 1
    assert any(it['name']=='FilterA' for it in data['items'])

    # filter by star_id
    async for db in get_db():
        res = await db.execute(select(StarModel).where(StarModel.name=='StarX'))
        star = res.scalars().first()
        sid = star.id
        break
    resp2 = await client.get(f'/api/v1/theater/movies/?star_id={sid}')
    assert resp2.status_code == 200
    assert any(it['name']=='FilterA' for it in resp2.json()['items'])

    # price range
    resp3 = await client.get('/api/v1/theater/movies/?price_min=5&price_max=6')
    assert resp3.status_code == 200
    assert any(it['name']=='FilterB' for it in resp3.json()['items'])

    # invalid sort_by -> fallback to id
    resp4 = await client.get('/api/v1/theater/movies/?sort_by=nonexistent')
    assert resp4.status_code == 200

    # favorites_only without auth -> 401
    resp5 = await client.get('/api/v1/theater/movies/?favorites_only=true')
    assert resp5.status_code == 401
