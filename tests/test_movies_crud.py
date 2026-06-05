import pytest
from uuid import uuid4

from database import get_db, MovieModel, CertificationModel


@pytest.mark.anyio
async def test_movies_crud(client, monkeypatch):
    # Override moderator requirement to bypass auth in test using FastAPI dependency override
    from main import app
    from security.deps import require_moderator
    app.dependency_overrides[require_moderator] = lambda: None
    monkeypatch.setattr(app, 'dependency_overrides', app.dependency_overrides)  # ensure cleanup

    async for db in get_db():
        cert = CertificationModel(name='R')
        db.add(cert)
        await db.flush()
        await db.commit()
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
        break

    resp = await client.post('/api/v1/movies/', json=movie_payload)
    assert resp.status_code == 201
    data = resp.json()
    movie_id = data['id']

    # update
    movie_payload['name'] = 'CRUD Movie Updated'
    resp = await client.patch(f'/api/v1/movies/{movie_id}/', json=movie_payload)
    assert resp.status_code == 200

    # delete
    resp = await client.delete(f'/api/v1/movies/{movie_id}/')
    assert resp.status_code == 200
    assert resp.json().get('deleted') is True
