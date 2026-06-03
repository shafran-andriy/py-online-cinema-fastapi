from typing import List, Type, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


essential = None

async def get_or_create_by_names(db: AsyncSession, Model: Type, names: List[str]) -> List:
    """Find existing Model instances by name and create missing ones. Returns list of instances.

    Args:
        db: AsyncSession
        Model: SQLAlchemy model class with ``name`` attribute
        names: list of names (strings)
    """
    names = [n.strip() for n in (names or []) if n and n.strip()]
    if not names:
        return []
    stmt = select(Model).where(Model.name.in_(names))
    res = await db.execute(stmt)
    existing = res.scalars().all()
    existing_names = {e.name for e in existing}
    missing = [n for n in names if n not in existing_names]
    new_objs = [Model(name=n) for n in missing]
    if new_objs:
        db.add_all(new_objs)
        await db.flush()
    return existing + new_objs


async def validate_ids(db: AsyncSession, Model: Type, ids: Optional[List[int]]) -> List:
    """Fetch Model instances by ids and validate all exist. Returns list of instances."""
    if not ids:
        return []
    stmt = select(Model).where(Model.id.in_(ids))
    res = await db.execute(stmt)
    objs = res.scalars().all()
    if len(objs) != len(set(ids)):
        raise ValueError("One or more ids invalid")
    return objs


async def prepare_related(db: AsyncSession,
                          GenreModel=None,
                          DirectorModel=None,
                          StarModel=None,
                          genre_ids: Optional[List[int]] = None,
                          director_ids: Optional[List[int]] = None,
                          star_ids: Optional[List[int]] = None,
                          genre_names: Optional[List[str]] = None,
                          director_names: Optional[List[str]] = None,
                          star_names: Optional[List[str]] = None):
    """Prepare related model instances (genres, directors, stars) from ids and/or names.
    Returns dict with keys 'genres','directors','stars' each a list of model instances.
    """
    result = {'genres': [], 'directors': [], 'stars': []}
    if GenreModel is not None:
        by_id = await validate_ids(db, GenreModel, genre_ids)
        by_name = await get_or_create_by_names(db, GenreModel, genre_names)
        # deduplicate by name
        seen = set(); merged = []
        for o in by_id + by_name:
            if o.name not in seen:
                seen.add(o.name); merged.append(o)
        result['genres'] = merged

    if DirectorModel is not None:
        by_id = await validate_ids(db, DirectorModel, director_ids)
        by_name = await get_or_create_by_names(db, DirectorModel, director_names)
        seen = set(); merged = []
        for o in by_id + by_name:
            if o.name not in seen:
                seen.add(o.name); merged.append(o)
        result['directors'] = merged

    if StarModel is not None:
        by_id = await validate_ids(db, StarModel, star_ids)
        by_name = await get_or_create_by_names(db, StarModel, star_names)
        seen = set(); merged = []
        for o in by_id + by_name:
            if o.name not in seen:
                seen.add(o.name); merged.append(o)
        result['stars'] = merged

    return result


async def sync_associations(db: AsyncSession, movie_id: int, movie_genres_table, movie_directors_table, movie_stars_table, *, genres: List = None, directors: List = None, stars: List = None):
    """Synchronize association tables for a movie: delete existing rows and insert provided ones.

    This bypasses ORM lazy-load issues and is intended for use in async endpoints or services.
    """
    # genres
    if genres is not None:
        await db.execute(movie_genres_table.delete().where(movie_genres_table.c.movie_id == movie_id))
        seen = set()
        for g in genres:
            if g.id not in seen:
                seen.add(g.id)
                await db.execute(movie_genres_table.insert().values(movie_id=movie_id, genre_id=g.id))
    # directors
    if directors is not None:
        await db.execute(movie_directors_table.delete().where(movie_directors_table.c.movie_id == movie_id))
        seen = set()
        for d in directors:
            if d.id not in seen:
                seen.add(d.id)
                await db.execute(movie_directors_table.insert().values(movie_id=movie_id, director_id=d.id))
    # stars
    if stars is not None:
        await db.execute(movie_stars_table.delete().where(movie_stars_table.c.movie_id == movie_id))
        seen = set()
        for s in stars:
            if s.id not in seen:
                seen.add(s.id)
                await db.execute(movie_stars_table.insert().values(movie_id=movie_id, star_id=s.id))
