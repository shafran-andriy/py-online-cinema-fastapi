"""
Tests for КРОК 2 new movie endpoints:
  2.1 GET /theater/movies/{id}/           — movie detail
  2.2 GET /theater/genres/                — genres with movies_count
  2.3 POST /theater/movies/{id}/like/     — like
      POST /theater/movies/{id}/dislike/  — dislike
      DELETE /theater/movies/{id}/like/   — cancel reaction
  2.4 POST /theater/movies/{id}/comments/ — add comment
      GET  /theater/movies/{id}/comments/ — list comments with replies
      POST /theater/movies/{id}/comments/{cid}/replies/ — reply
      DELETE /theater/comments/{cid}/     — delete comment
  2.5 POST /theater/movies/{id}/rate/     — rate
      DELETE /theater/movies/{id}/rate/   — delete rating
  2.6 GET  /notifications/                — list notifications
      PATCH /notifications/{id}/read/     — mark read
  2.7 DELETE /theater/movies/{id}/        — guarded; passes when no purchases
"""

import asyncio
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import (
    get_db,
    MovieModel,
    CertificationModel,
    UserModel,
    UserGroupModel,
    NotificationModel,
)
from main import app
from security.deps import require_moderator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure dependency overrides are cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


async def _create_cert_and_movie(db_session, cert_name="G", movie_name="Test Movie"):
    """Create a certification + movie directly in DB. Returns (cert, movie)."""
    cert = CertificationModel(name=cert_name)
    db_session.add(cert)
    await db_session.flush()

    movie = MovieModel(
        name=movie_name, year=2020, time=90, imdb=7.0,
        votes=100, description="A test film", price=9.99,
        certification_id=cert.id,
    )
    db_session.add(movie)
    await db_session.flush()
    await db_session.commit()
    return cert, movie


async def _seed_db():
    """Helper to create cert + movie and return their IDs."""
    async for db in get_db():
        cert, movie = await _create_cert_and_movie(db)
        return cert.id, movie.id


async def _register_activate_login(client: AsyncClient, email: str, password="StrongP@ss1!") -> str:
    """Register, activate and login a user. Returns access_token."""
    r = await client.post("/api/v1/accounts/register/", json={"email": email, "password": password})
    assert r.status_code == 201, r.text

    # Activate: find token in DB
    async for db in get_db():
        from database import ActivationTokenModel
        res = await db.execute(
            select(ActivationTokenModel).join(UserModel).where(UserModel.email == email)
        )
        token_obj = res.scalars().first()
        assert token_obj, "Activation token not created"
        token = token_obj.token
        break

    r = await client.post("/api/v1/accounts/activate/", json={"email": email, "token": token})
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/accounts/login/", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _make_moderator(email: str):
    async for db in get_db():
        res = await db.execute(select(UserGroupModel).where(UserGroupModel.name == "moderator"))
        mod_group = res.scalars().first()
        res2 = await db.execute(select(UserModel).where(UserModel.email == email))
        user = res2.scalars().first()
        user.group_id = mod_group.id
        await db.commit()
        break


# ---------------------------------------------------------------------------
# 2.1 Movie Detail
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_movie_detail_not_found(client):
    r = await client.get("/api/v1/theater/movies/99999/")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_movie_detail_ok(client):
    cert_id, movie_id = await _seed_db()
    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == movie_id
    assert "avg_rating" in data
    assert "likes_count" in data
    assert "dislikes_count" in data
    assert "genres" in data
    assert "directors" in data
    assert "stars" in data
    assert "certification" in data


# ---------------------------------------------------------------------------
# 2.2 Genre list with movies_count
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_genres_with_count_empty(client):
    r = await client.get("/api/v1/theater/genres/")
    assert r.status_code == 200
    items = r.json()
    # may be empty or have genres from other tests (DB reset each test)
    for item in items:
        assert "movies_count" in item
        assert isinstance(item["movies_count"], int)


@pytest.mark.anyio
async def test_genres_with_count_nonzero(client):
    """Create genre + movie linked to it; count should be ≥ 1."""
    # bypass moderator check to create via API
    app.dependency_overrides[require_moderator] = lambda: None
    cert_id, movie_id = await _seed_db()

    async for db in get_db():
        from database.models.movies import GenreModel, movie_genres
        genre = GenreModel(name="ActionTest")
        db.add(genre)
        await db.flush()
        await db.execute(movie_genres.insert().values(movie_id=movie_id, genre_id=genre.id))
        await db.commit()
        genre_id = genre.id
        break

    r = await client.get("/api/v1/theater/genres/")
    assert r.status_code == 200
    matched = [g for g in r.json() if g["name"] == "ActionTest"]
    assert matched, "Genre not in response"
    assert matched[0]["movies_count"] == 1


# ---------------------------------------------------------------------------
# 2.3 Like / Dislike
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_like_requires_auth(client):
    _, movie_id = await _seed_db()
    r = await client.post(f"/api/v1/theater/movies/{movie_id}/like/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_like_dislike_cancel(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "liker@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # like
    r = await client.post(f"/api/v1/theater/movies/{movie_id}/like/", headers=headers)
    assert r.status_code == 200
    assert r.json()["liked"] is True

    # detail: likes_count == 1
    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.json()["likes_count"] == 1
    assert r.json()["dislikes_count"] == 0

    # switch to dislike (upsert replaces)
    r = await client.post(f"/api/v1/theater/movies/{movie_id}/dislike/", headers=headers)
    assert r.status_code == 200
    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.json()["likes_count"] == 0
    assert r.json()["dislikes_count"] == 1

    # cancel
    r = await client.delete(f"/api/v1/theater/movies/{movie_id}/like/", headers=headers)
    assert r.status_code == 200
    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.json()["dislikes_count"] == 0


@pytest.mark.anyio
async def test_like_movie_not_found(client):
    token = await _register_activate_login(client, "liker2@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post("/api/v1/theater/movies/99999/like/", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2.4 Comments + Replies
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_comment_requires_auth(client):
    _, movie_id = await _seed_db()
    r = await client.post(f"/api/v1/theater/movies/{movie_id}/comments/", json={"body": "Hello"})
    assert r.status_code == 403


@pytest.mark.anyio
async def test_add_and_list_comments(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "commenter@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "Great movie!"},
        headers=headers,
    )
    assert r.status_code == 201
    comment_id = r.json()["id"]
    assert r.json()["parent_id"] is None

    r = await client.get(f"/api/v1/theater/movies/{movie_id}/comments/")
    assert r.status_code == 200
    comments = r.json()
    assert any(c["id"] == comment_id for c in comments)


@pytest.mark.anyio
async def test_reply_creates_notification(client):
    _, movie_id = await _seed_db()
    # Author writes a comment
    token_author = await _register_activate_login(client, "author@test.com")
    token_replier = await _register_activate_login(client, "replier@test.com")

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "Original comment"},
        headers={"Authorization": f"Bearer {token_author}"},
    )
    assert r.status_code == 201
    comment_id = r.json()["id"]

    # Replier replies
    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/{comment_id}/replies/",
        json={"body": "My reply"},
        headers={"Authorization": f"Bearer {token_replier}"},
    )
    assert r.status_code == 201
    reply = r.json()
    assert reply["parent_id"] == comment_id

    # Author sees notification
    r = await client.get("/api/v1/notifications/", headers={"Authorization": f"Bearer {token_author}"})
    assert r.status_code == 200
    notifs = r.json()
    assert len(notifs) >= 1
    assert any(n["type"] == "reply" for n in notifs)


@pytest.mark.anyio
async def test_no_self_reply_notification(client):
    """Reply to own comment should NOT create a notification."""
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "self_replier@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "My own comment"},
        headers=headers,
    )
    comment_id = r.json()["id"]

    await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/{comment_id}/replies/",
        json={"body": "Replying to myself"},
        headers=headers,
    )

    r = await client.get("/api/v1/notifications/", headers=headers)
    notifs = r.json()
    # no notification for self-reply
    assert not any(n["type"] == "reply" for n in notifs)


@pytest.mark.anyio
async def test_delete_own_comment(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "deleter@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "Delete me"},
        headers=headers,
    )
    comment_id = r.json()["id"]

    r = await client.delete(f"/api/v1/theater/comments/{comment_id}/", headers=headers)
    assert r.status_code == 200
    assert r.json()["deleted"] is True


@pytest.mark.anyio
async def test_delete_comment_forbidden_for_other_user(client):
    _, movie_id = await _seed_db()
    token_a = await _register_activate_login(client, "owner_comment@test.com")
    token_b = await _register_activate_login(client, "other_comment@test.com")

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "Mine"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    comment_id = r.json()["id"]

    r = await client.delete(
        f"/api/v1/theater/comments/{comment_id}/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_moderator_can_delete_any_comment(client):
    _, movie_id = await _seed_db()
    token_user = await _register_activate_login(client, "comment_poster@test.com")
    mod_email = "mod_del@test.com"
    token_mod = await _register_activate_login(client, mod_email)
    await _make_moderator(mod_email)

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "User comment"},
        headers={"Authorization": f"Bearer {token_user}"},
    )
    comment_id = r.json()["id"]

    r = await client.delete(
        f"/api/v1/theater/comments/{comment_id}/",
        headers={"Authorization": f"Bearer {token_mod}"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 2.5 Rating
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_rate_movie(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "rater@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(f"/api/v1/theater/movies/{movie_id}/rate/", json={"score": 8}, headers=headers)
    assert r.status_code == 200
    assert r.json()["score"] == 8

    # Detail shows avg_rating
    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.json()["avg_rating"] == 8.0


@pytest.mark.anyio
async def test_rate_out_of_range(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "rater2@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(f"/api/v1/theater/movies/{movie_id}/rate/", json={"score": 11}, headers=headers)
    assert r.status_code == 422


@pytest.mark.anyio
async def test_rate_upsert(client):
    """Second rating replaces first."""
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "rater3@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(f"/api/v1/theater/movies/{movie_id}/rate/", json={"score": 5}, headers=headers)
    await client.post(f"/api/v1/theater/movies/{movie_id}/rate/", json={"score": 9}, headers=headers)

    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.json()["avg_rating"] == 9.0


@pytest.mark.anyio
async def test_delete_rating(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "rater4@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(f"/api/v1/theater/movies/{movie_id}/rate/", json={"score": 7}, headers=headers)
    r = await client.delete(f"/api/v1/theater/movies/{movie_id}/rate/", headers=headers)
    assert r.status_code == 200

    r = await client.get(f"/api/v1/theater/movies/{movie_id}/")
    assert r.json()["avg_rating"] is None


# ---------------------------------------------------------------------------
# 2.6 Notifications
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_notifications_requires_auth(client):
    r = await client.get("/api/v1/notifications/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_mark_notification_read(client):
    _, movie_id = await _seed_db()
    token_author = await _register_activate_login(client, "notif_author@test.com")
    token_replier = await _register_activate_login(client, "notif_replier@test.com")

    # create comment → reply → triggers notification
    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "Notification test comment"},
        headers={"Authorization": f"Bearer {token_author}"},
    )
    comment_id = r.json()["id"]
    await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/{comment_id}/replies/",
        json={"body": "Reply triggers notif"},
        headers={"Authorization": f"Bearer {token_replier}"},
    )

    # get notifications
    r = await client.get("/api/v1/notifications/", headers={"Authorization": f"Bearer {token_author}"})
    notifs = r.json()
    assert notifs
    notif_id = notifs[0]["id"]
    assert notifs[0]["is_read"] is False

    # mark as read
    r = await client.patch(
        f"/api/v1/notifications/{notif_id}/read/",
        headers={"Authorization": f"Bearer {token_author}"},
    )
    assert r.status_code == 200
    assert r.json()["is_read"] is True


@pytest.mark.anyio
async def test_mark_others_notification_forbidden(client):
    _, movie_id = await _seed_db()
    token_a = await _register_activate_login(client, "notif_a@test.com")
    token_b = await _register_activate_login(client, "notif_b@test.com")

    r = await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/",
        json={"body": "A comment"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    comment_id = r.json()["id"]
    await client.post(
        f"/api/v1/theater/movies/{movie_id}/comments/{comment_id}/replies/",
        json={"body": "Triggers notif for A"},
        headers={"Authorization": f"Bearer {token_b}"},
    )

    r = await client.get("/api/v1/notifications/", headers={"Authorization": f"Bearer {token_a}"})
    notif_id = r.json()[0]["id"]

    # user B tries to mark A's notification — should be 403
    r = await client.patch(
        f"/api/v1/notifications/{notif_id}/read/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 2.7 Prevent delete if purchased (stub: always allowed right now)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_movie_not_purchased(client):
    """Movie with no purchases can be deleted by moderator."""
    _, movie_id = await _seed_db()
    mod_email = "mod_delete@test.com"
    token_mod = await _register_activate_login(client, mod_email)
    await _make_moderator(mod_email)

    r = await client.delete(
        f"/api/v1/theater/movies/{movie_id}/",
        headers={"Authorization": f"Bearer {token_mod}"},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] is True


@pytest.mark.anyio
async def test_delete_movie_requires_moderator(client):
    _, movie_id = await _seed_db()
    token = await _register_activate_login(client, "regular_del@test.com")
    r = await client.delete(
        f"/api/v1/theater/movies/{movie_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
