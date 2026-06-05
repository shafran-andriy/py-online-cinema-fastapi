import pytest

from main import app
from security.deps import require_moderator


@pytest.mark.anyio
async def test_create_movie_invalid_cert(client):
    # bypass moderator dependency for test
    app.dependency_overrides[require_moderator] = lambda: None

    payload = {
        'name': 'InvalidCert',
        'year': 2020,
        'time': 100,
        'imdb': 5.0,
        'votes': 10,
        'description': 'Invalid cert test',
        'price': 1.99,
        'certification_id': 99999999,
    }

    resp = await client.post('/api/v1/movies/', json=payload)
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_update_movie_not_found(client):
    app.dependency_overrides[require_moderator] = lambda: None
    payload = {'name': 'NoMovie'}
    resp = await client.patch('/api/v1/movies/9999999/', json=payload)
    assert resp.status_code == 404
