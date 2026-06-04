#!/bin/sh
set -e

# Wait for database to be available using SQLAlchemy async engine
python - <<'PY'
import os, sys, asyncio
from sqlalchemy.ext.asyncio import create_async_engine

url = os.environ.get('DATABASE_URL')
if not url:
    print('DATABASE_URL not set', file=sys.stderr)
    sys.exit(1)

async def wait_db():
    for i in range(60):
        try:
            engine = create_async_engine(url)
            async with engine.connect() as conn:
                await conn.run_sync(lambda conn: None)
            await engine.dispose()
            print('DB available')
            return
        except Exception as e:
            print('Waiting for DB...')
            await asyncio.sleep(1)
    raise SystemExit('DB did not become ready')

asyncio.run(wait_db())
PY

alembic upgrade head
