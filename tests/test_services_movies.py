import pytest
from database import GenreModel, DirectorModel, StarModel, MovieModel, CertificationModel
from services.movies_service import get_or_create_by_names, prepare_related, sync_associations
from database.models.movies import movie_genres, movie_directors, movie_stars
from database import get_db
from sqlalchemy import select


@pytest.mark.anyio
async def test_get_or_create_by_names_and_prepare(tmp_path):
    async for db in get_db():
        # ensure some existing entries
        g1 = GenreModel(name='ExistG')
        d1 = DirectorModel(name='ExistD')
        s1 = StarModel(name='ExistS')
        db.add_all([g1, d1, s1])
        await db.flush()
        # call service to get existing + new
        genres = await get_or_create_by_names(db, GenreModel, ['ExistG', 'NewG'])
        directors = await get_or_create_by_names(db, DirectorModel, ['ExistD', 'NewD'])
        stars = await get_or_create_by_names(db, StarModel, ['ExistS', 'NewS'])
        # check names present
        assert any(g.name == 'ExistG' for g in genres)
        assert any(g.name == 'NewG' for g in genres)
        assert any(d.name == 'ExistD' for d in directors)
        assert any(s.name == 'NewS' for s in stars)
        await db.commit()
        break


@pytest.mark.anyio
async def test_sync_associations_creates_rows(client):
    # create movie and related objects
    async for db in get_db():
        cert = CertificationModel(name='SYNC')
        g1 = GenreModel(name='G1')
        d1 = DirectorModel(name='DR1')
        s1 = StarModel(name='ST1')
        db.add_all([cert, g1, d1, s1])
        await db.flush()
        movie = MovieModel(name='SyncMovie', year=2000, time=100, imdb=5.0, votes=1, description='x', price=1.0, certification_id=cert.id)
        db.add(movie)
        await db.flush()
        # call sync
        await sync_associations(db, movie.id, movie_genres, movie_directors, movie_stars, genres=[g1], directors=[d1], stars=[s1])
        await db.commit()
        # verify
        stmt = select(MovieModel).where(MovieModel.id == movie.id).options()
        res = await db.execute(select(MovieModel).where(MovieModel.id == movie.id))
        m = res.scalars().first()
        # query association tables directly
        resg = await db.execute(select(movie_genres).where(movie_genres.c.movie_id == movie.id))
        rows = resg.all()
        assert len(rows) == 1
        break
