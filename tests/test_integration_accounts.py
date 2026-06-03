import pytest

from httpx import AsyncClient


@pytest.mark.anyio
async def test_register_activate_login_flow(client: AsyncClient):
    # Register
    resp = await client.post('/api/v1/accounts/register/', json={'email': 'test@example.com', 'password': 'StrongP@ssw0rd'})
    assert resp.status_code == 201
    data = resp.json()
    assert data['email'] == 'test@example.com'

    # Retrieve activation token from DB via an endpoint is not present; instead, request password reset to ensure email sender used
    # For test simplicity, request password reset (which triggers email) and then simulate reset using stored token in DB
    resp = await client.post('/api/v1/accounts/password-reset/request/', json={'email': 'test@example.com'})
    assert resp.status_code == 200
    # Now try login before activation should fail
    resp = await client.post('/api/v1/accounts/login/', json={'email': 'test@example.com', 'password': 'StrongP@ssw0rd'})
    assert resp.status_code == 400

    # Activate using activation token fetched directly from DB
    # Access DB to get token
    from database import get_db
    from database import ActivationTokenModel, UserModel
    async for db in get_db():
        res = await db.execute(ActivationTokenModel.__table__.select())
        row = res.first()
        assert row is not None
        token = row[1]  # token column
        # get email
        res2 = await db.execute(UserModel.__table__.select().where(UserModel.id == row[3]))
        user_row = res2.first()
        assert user_row is not None
        email = user_row[1]
        break

    resp = await client.post('/api/v1/accounts/activate/', json={'email': email, 'token': token})
    assert resp.status_code == 200

    # Login should succeed now
    resp = await client.post('/api/v1/accounts/login/', json={'email': 'test@example.com', 'password': 'StrongP@ssw0rd'})
    assert resp.status_code == 200
    tokens = resp.json()
    assert 'access_token' in tokens and 'refresh_token' in tokens

    # Refresh access token
    resp = await client.post('/api/v1/accounts/token/refresh/', json={'refresh_token': tokens['refresh_token']})
    assert resp.status_code == 200
    assert 'access_token' in resp.json()

    # Logout
    resp = await client.post('/api/v1/accounts/logout/', json={'refresh_token': tokens['refresh_token']})
    assert resp.status_code == 200

    # Using refresh token after logout should fail
    resp = await client.post('/api/v1/accounts/token/refresh/', json={'refresh_token': tokens['refresh_token']})
    assert resp.status_code == 400
