import pytest
from database import GenreModel, MovieModel, CertificationModel
from database import get_db
from sqlalchemy import select


@pytest.mark.anyio
async def test_search_and_favorites(client):
    # prepare data
    async for db in get_db():
        cert = CertificationModel(name='SF')
        g1 = GenreModel(name='SearchG')
        db.add_all([cert, g1])
        await db.flush()
        m1 = MovieModel(name='FindMe', year=2021, time=100, imdb=8.0, votes=100, description='searchable', price=3.0, certification_id=cert.id)
        m2 = MovieModel(name='Other', year=2020, time=90, imdb=6.0, votes=50, description='nope', price=2.0, certification_id=cert.id)
        db.add_all([m1, m2])
        await db.flush()
        # associate genre to m1
        from database.models.movies import movie_genres
        await db.execute(movie_genres.insert().values(movie_id=m1.id, genre_id=g1.id))
        await db.commit()
        break

    # search q
    resp = await client.get('/api/v1/theater/movies/?q=Find')
    assert resp.status_code == 200
    data = resp.json()
    assert any(item['name'] == 'FindMe' for item in data)

    # favorite movie (need a user) - reuse test user register/activate
    payload = {"email": "favuser@example.com", "password": "StrongPass1!"}
    r = await client.post('/api/v1/accounts/register/', json=payload)
    assert r.status_code == 201
    # activate
    async for db in get_db():
        res = await db.execute(select(CertificationModel))
        break
    # simulate activation by finding token
    async for db in get_db():
        from database import ActivationTokenModel, UserModel
        res = await db.execute(select(ActivationTokenModel).join(UserModel).where(UserModel.email == payload['email']))
        t = res.scalars().first()
        token = t.token
        break
    r2 = await client.post('/api/v1/accounts/activate/', json={"email": payload['email'], "token": token})
    assert r2.status_code == 200
    # login
    r3 = await client.post('/api/v1/accounts/login/', json=payload)
    tok = r3.json()['access_token']

    headers = {'Authorization': f'Bearer {tok}'}
    # favorite movie id m1
    async for db in get_db():
        res = await db.execute(select(MovieModel).where(MovieModel.name == 'FindMe'))
        movie = res.scalars().first()
        mid = movie.id
        break

    rf = await client.post(f'/api/v1/theater/movies/{mid}/favorite/', headers=headers)
    assert rf.status_code == 201

    # list favorites
    lf = await client.get('/api/v1/theater/movies/favorites/', headers=headers)
    assert lf.status_code == 200
    fd = lf.json()
    assert any(m['id'] == mid for m in fd)

    # remove favorite
    rm = await client.delete(f'/api/v1/theater/movies/{mid}/favorite/', headers=headers)
    assert rm.status_code == 200

    lf2 = await client.get('/api/v1/theater/movies/favorites/', headers=headers)
    assert not any(m['id'] == mid for m in lf2.json())
