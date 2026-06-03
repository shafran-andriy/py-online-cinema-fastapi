"""
Tests for new auth endpoints:
  1.1 POST /accounts/change-password/
  1.2 GET  /accounts/users/
      PATCH /accounts/users/{id}/group/
      PATCH /accounts/users/{id}/activate/
  1.3 GET  /profiles/me/
      PATCH /profiles/me/
  1.4 POST /accounts/activation/resend/
"""
import io
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import get_db, UserModel, UserGroupModel, ActivationTokenModel


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _register(client: AsyncClient, email: str, password: str = "StrongP@ssw0rd") -> None:
    resp = await client.post("/api/v1/accounts/register/", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text


async def _get_activation_token(email: str) -> str:
    """Fetch the activation token for a given email directly from the DB."""
    async for db in get_db():
        res = await db.execute(
            select(ActivationTokenModel)
            .join(UserModel, UserModel.id == ActivationTokenModel.user_id)
            .where(UserModel.email == email)
        )
        token_record = res.scalars().first()
        assert token_record is not None, f"No activation token found for {email}"
        return token_record.token


async def _activate(client: AsyncClient, email: str) -> None:
    token = await _get_activation_token(email)
    resp = await client.post("/api/v1/accounts/activate/", json={"email": email, "token": token})
    assert resp.status_code == 200, resp.text


async def _login(client: AsyncClient, email: str, password: str = "StrongP@ssw0rd") -> str:
    """Register (optionally), activate, login and return access token."""
    resp = await client.post("/api/v1/accounts/login/", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _make_admin(email: str) -> None:
    """Elevate a user to admin directly in the DB (bypasses endpoints)."""
    async for db in get_db():
        res = await db.execute(select(UserGroupModel).where(UserGroupModel.name == "admin"))
        admin_group = res.scalars().first()
        res2 = await db.execute(select(UserModel).where(UserModel.email == email))
        user = res2.scalars().first()
        user.group_id = admin_group.id
        await db.commit()
        break


async def _setup_active_user(client: AsyncClient, email: str, password: str = "StrongP@ssw0rd") -> str:
    """Register → activate → login → return access_token."""
    await _register(client, email, password)
    await _activate(client, email)
    return await _login(client, email, password)


# ─── 1.4 · Resend Activation ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_resend_activation_unknown_email(client: AsyncClient):
    resp = await client.post("/api/v1/accounts/activation/resend/", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert "will receive" in resp.json()["message"]


@pytest.mark.anyio
async def test_resend_activation_already_active_user(client: AsyncClient):
    await _setup_active_user(client, "active@example.com")
    resp = await client.post("/api/v1/accounts/activation/resend/", json={"email": "active@example.com"})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_resend_activation_creates_new_token(client: AsyncClient):
    email = "resend@example.com"
    await _register(client, email)

    old_token = await _get_activation_token(email)

    resp = await client.post("/api/v1/accounts/activation/resend/", json={"email": email})
    assert resp.status_code == 200

    new_token = await _get_activation_token(email)
    assert new_token != old_token, "Resend should issue a new token"


@pytest.mark.anyio
async def test_resend_activation_new_token_works(client: AsyncClient):
    email = "resend2@example.com"
    await _register(client, email)
    await client.post("/api/v1/accounts/activation/resend/", json={"email": email})

    new_token = await _get_activation_token(email)
    resp = await client.post("/api/v1/accounts/activate/", json={"email": email, "token": new_token})
    assert resp.status_code == 200


# ─── 1.1 · Change Password ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_change_password_unauthenticated(client: AsyncClient):
    resp = await client.post(
        "/api/v1/accounts/change-password/",
        json={"old_password": "StrongP@ssw0rd", "new_password": "N3wStr0ng!"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_change_password_wrong_old_password(client: AsyncClient):
    token = await _setup_active_user(client, "chpw_wrong@example.com")
    resp = await client.post(
        "/api/v1/accounts/change-password/",
        json={"old_password": "WrongPass1!", "new_password": "N3wStr0ng!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "incorrect" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_change_password_weak_new_password(client: AsyncClient):
    token = await _setup_active_user(client, "chpw_weak@example.com")
    resp = await client.post(
        "/api/v1/accounts/change-password/",
        json={"old_password": "StrongP@ssw0rd", "new_password": "weak"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_change_password_success(client: AsyncClient):
    email = "chpw_ok@example.com"
    old_pw, new_pw = "StrongP@ssw0rd", "N3wStr0ng!Pass"
    token = await _setup_active_user(client, email, old_pw)

    resp = await client.post(
        "/api/v1/accounts/change-password/",
        json={"old_password": old_pw, "new_password": new_pw},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Password changed successfully."

    # Old password no longer works
    resp = await client.post("/api/v1/accounts/login/", json={"email": email, "password": old_pw})
    assert resp.status_code == 400

    # New password works
    resp = await client.post("/api/v1/accounts/login/", json={"email": email, "password": new_pw})
    assert resp.status_code == 200


# ─── 1.2 · Admin: List Users ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_users_forbidden_for_regular_user(client: AsyncClient):
    token = await _setup_active_user(client, "regular@example.com")
    resp = await client.get("/api/v1/accounts/users/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_list_users_success_for_admin(client: AsyncClient):
    email = "admin_list@example.com"
    token = await _setup_active_user(client, email)
    await _make_admin(email)
    token = await _login(client, email)

    resp = await client.get("/api/v1/accounts/users/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert all("id" in u and "email" in u and "group" in u for u in data)


# ─── 1.2 · Admin: Change Group ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_change_group_forbidden_for_regular_user(client: AsyncClient):
    token = await _setup_active_user(client, "reg_chgrp@example.com")
    resp = await client.patch(
        "/api/v1/accounts/users/1/group/",
        json={"group": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_change_group_not_found(client: AsyncClient):
    admin_email = "admin_chgrp@example.com"
    token = await _setup_active_user(client, admin_email)
    await _make_admin(admin_email)
    token = await _login(client, admin_email)

    resp = await client.patch(
        "/api/v1/accounts/users/99999/group/",
        json={"group": "moderator"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_change_group_success(client: AsyncClient):
    target_email = "target_grp@example.com"
    admin_email = "admin_grp@example.com"

    await _register(client, target_email)
    await _activate(client, target_email)
    admin_token = await _setup_active_user(client, admin_email)
    await _make_admin(admin_email)
    admin_token = await _login(client, admin_email)

    # get target user id
    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.email == target_email))
        target = res.scalars().first()
        target_id = target.id
        break

    resp = await client.patch(
        f"/api/v1/accounts/users/{target_id}/group/",
        json={"group": "moderator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert "moderator" in resp.json()["message"]

    # verify in DB
    async for db in get_db():
        from sqlalchemy.orm import selectinload
        res = await db.execute(
            select(UserModel).options(selectinload(UserModel.group)).where(UserModel.id == target_id)
        )
        user = res.scalars().first()
        assert user.group.name.value == "moderator"
        break


# ─── 1.2 · Admin: Manual Activate ────────────────────────────────────────────

@pytest.mark.anyio
async def test_manual_activate_forbidden_for_regular_user(client: AsyncClient):
    token = await _setup_active_user(client, "reg_act@example.com")
    resp = await client.patch(
        "/api/v1/accounts/users/1/activate/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_manual_activate_success(client: AsyncClient):
    target_email = "inactive_target@example.com"
    admin_email = "admin_manact@example.com"

    await _register(client, target_email)
    admin_token = await _setup_active_user(client, admin_email)
    await _make_admin(admin_email)
    admin_token = await _login(client, admin_email)

    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.email == target_email))
        target = res.scalars().first()
        target_id = target.id
        assert not target.is_active
        break

    resp = await client.patch(
        f"/api/v1/accounts/users/{target_id}/activate/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.id == target_id))
        user = res.scalars().first()
        assert user.is_active
        break


@pytest.mark.anyio
async def test_manual_activate_already_active(client: AsyncClient):
    target_email = "already_active@example.com"
    admin_email = "admin_aa@example.com"

    await _setup_active_user(client, target_email)
    admin_token = await _setup_active_user(client, admin_email)
    await _make_admin(admin_email)
    admin_token = await _login(client, admin_email)

    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.email == target_email))
        target = res.scalars().first()
        target_id = target.id
        break

    resp = await client.patch(
        f"/api/v1/accounts/users/{target_id}/activate/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
    assert "already active" in resp.json()["detail"].lower()


# ─── 1.3 · Profiles ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_profile_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/profiles/me/")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_profile_auto_creates_empty_profile(client: AsyncClient):
    token = await _setup_active_user(client, "profile_get@example.com")
    resp = await client.get("/api/v1/profiles/me/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_name"] is None
    assert data["last_name"] is None
    assert data["avatar"] is None


@pytest.mark.anyio
async def test_get_profile_idempotent(client: AsyncClient):
    """Calling GET /me/ twice should not create duplicate profiles."""
    token = await _setup_active_user(client, "profile_idem@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp1 = await client.get("/api/v1/profiles/me/", headers=headers)
    resp2 = await client.get("/api/v1/profiles/me/", headers=headers)
    assert resp1.status_code == resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]


@pytest.mark.anyio
async def test_update_profile_partial(client: AsyncClient):
    token = await _setup_active_user(client, "profile_patch@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(
        "/api/v1/profiles/me/",
        json={"first_name": "Alice", "last_name": "Smith"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_name"] == "Alice"
    assert data["last_name"] == "Smith"
    assert data["gender"] is None


@pytest.mark.anyio
async def test_update_profile_gender_and_dob(client: AsyncClient):
    token = await _setup_active_user(client, "profile_gender@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(
        "/api/v1/profiles/me/",
        json={"gender": "woman", "date_of_birth": "1990-05-15"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["gender"] == "woman"
    assert data["date_of_birth"] == "1990-05-15"


@pytest.mark.anyio
async def test_update_profile_invalid_gender(client: AsyncClient):
    token = await _setup_active_user(client, "profile_badgender@example.com")
    resp = await client.patch(
        "/api/v1/profiles/me/",
        json={"gender": "robot"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_upload_avatar_invalid_type(client: AsyncClient):
    from config.dependencies import get_s3_storage_client
    from storages import S3StorageInterface

    class DummyS3(S3StorageInterface):
        async def upload_fileobj(self, data, key, content_type="application/octet-stream"):
            return f"http://minio/test/{key}"

    from main import app
    app.dependency_overrides[get_s3_storage_client] = lambda: DummyS3()

    token = await _setup_active_user(client, "avatar_bad@example.com")
    resp = await client.post(
        "/api/v1/profiles/me/avatar/",
        files={"file": ("doc.pdf", b"PDF content", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_s3_storage_client, None)
    assert resp.status_code == 400
    assert "Invalid file type" in resp.json()["detail"]


@pytest.mark.anyio
async def test_upload_avatar_success(client: AsyncClient):
    from config.dependencies import get_s3_storage_client
    from storages import S3StorageInterface

    class DummyS3(S3StorageInterface):
        async def upload_fileobj(self, data, key, content_type="application/octet-stream"):
            return f"http://minio/avatars/{key}"

    from main import app
    app.dependency_overrides[get_s3_storage_client] = lambda: DummyS3()

    token = await _setup_active_user(client, "avatar_ok@example.com")
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal PNG header
    resp = await client.post(
        "/api/v1/profiles/me/avatar/",
        files={"file": ("avatar.png", fake_png, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_s3_storage_client, None)
    assert resp.status_code == 200
    data = resp.json()
    assert data["avatar"] is not None
    assert "minio" in data["avatar"]
