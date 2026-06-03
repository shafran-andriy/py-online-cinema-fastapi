import pytest
from database import ActivationTokenModel, UserModel
from database import get_db
from services.accounts import delete_expired_activation_tokens
from datetime import datetime, timezone, timedelta
from sqlalchemy import select


@pytest.mark.anyio
async def test_delete_expired_activation_tokens():
    async for db in get_db():
        # create two users
        u1 = UserModel.create(email='exp1@test.com', raw_password='Strong1!', group_id=1)
        u2 = UserModel.create(email='valid@test.com', raw_password='Strong1!', group_id=1)
        db.add_all([u1, u2])
        await db.flush()
        # create tokens: expired for u1, valid for u2
        expired = ActivationTokenModel(user_id=u1.id, expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        valid = ActivationTokenModel(user_id=u2.id, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        db.add_all([expired, valid])
        await db.commit()
        # run deletion
        deleted = await delete_expired_activation_tokens(db)
        # verify expired token removed
        async for db2 in get_db():
            res = await db2.execute(select(ActivationTokenModel).where(ActivationTokenModel.token == expired.token))
            assert res.scalars().first() is None
            res2 = await db2.execute(select(ActivationTokenModel).where(ActivationTokenModel.token == valid.token))
            assert res2.scalars().first() is not None
            break
        break
