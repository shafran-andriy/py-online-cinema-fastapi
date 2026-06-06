from typing import List, Type, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_create_by_names(db: AsyncSession, Model: Type, names: List[str]) -> List:
    """Find existing Model instances by name and create missing ones. Returns list of instances."""
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
    return list(existing) + new_objs


async def validate_ids(db: AsyncSession, Model: Type, ids: Optional[List[int]]) -> List:
    """Fetch Model instances by ids and validate all exist. Returns list of instances."""
    if not ids:
        return []
    stmt = select(Model).where(Model.id.in_(ids))
    res = await db.execute(stmt)
    objs = list(res.scalars().all())
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
    """Prepare related model instances (genres, directors, stars) from ids and/or names."""
    result: dict[str, list] = {'genres': [], 'directors': [], 'stars': []}
    if GenreModel is not None:
        by_id = await validate_ids(db, GenreModel, genre_ids)
        by_name = await get_or_create_by_names(db, GenreModel, genre_names)
        seen = set()
        merged = []
        for o in by_id + by_name:
            if o.name not in seen:
                seen.add(o.name)
                merged.append(o)
        result['genres'] = merged

    if DirectorModel is not None:
        by_id = await validate_ids(db, DirectorModel, director_ids)
        by_name = await get_or_create_by_names(db, DirectorModel, director_names)
        seen = set()
        merged = []
        for o in by_id + by_name:
            if o.name not in seen:
                seen.add(o.name)
                merged.append(o)
        result['directors'] = merged

    if StarModel is not None:
        by_id = await validate_ids(db, StarModel, star_ids)
        by_name = await get_or_create_by_names(db, StarModel, star_names)
        seen = set()
        merged = []
        for o in by_id + by_name:
            if o.name not in seen:
                seen.add(o.name)
                merged.append(o)
        result['stars'] = merged

    return result


async def sync_associations(
    db: AsyncSession,
    movie_id: int,
    movie_genres_table,
    movie_directors_table,
    movie_stars_table,
    *,
    genres: List = None,
    directors: List = None,
    stars: List = None,
):
    """Synchronize association tables for a movie."""
    if genres is not None:
        await db.execute(movie_genres_table.delete().where(movie_genres_table.c.movie_id == movie_id))
        seen = set()
        for g in genres:
            if g.id not in seen:
                seen.add(g.id)
                await db.execute(movie_genres_table.insert().values(movie_id=movie_id, genre_id=g.id))
    if directors is not None:
        await db.execute(movie_directors_table.delete().where(movie_directors_table.c.movie_id == movie_id))
        seen = set()
        for d in directors:
            if d.id not in seen:
                seen.add(d.id)
                await db.execute(movie_directors_table.insert().values(movie_id=movie_id, director_id=d.id))
    if stars is not None:
        await db.execute(movie_stars_table.delete().where(movie_stars_table.c.movie_id == movie_id))
        seen = set()
        for s in stars:
            if s.id not in seen:
                seen.add(s.id)
                await db.execute(movie_stars_table.insert().values(movie_id=movie_id, star_id=s.id))


async def create_movie(
    db: AsyncSession,
    payload,
    *,
    MovieModel,
    GenreModel,
    DirectorModel,
    StarModel,
    CertificationModel,
    movie_genres,
    movie_directors,
    movie_stars,
):
    """Create movie with related genres/directors/stars. Raises ValueError on validation errors."""
    cert = await db.get(CertificationModel, payload.certification_id)
    if not cert:
        raise ValueError("Invalid certification_id")

    movie = MovieModel(
        name=payload.name,
        year=payload.year,
        time=payload.time,
        imdb=payload.imdb,
        votes=payload.votes,
        description=payload.description,
        price=payload.price,
        certification_id=payload.certification_id,
    )
    db.add(movie)
    await db.flush()

    related = await prepare_related(
        db,
        GenreModel=GenreModel,
        DirectorModel=DirectorModel,
        StarModel=StarModel,
        genre_ids=getattr(payload, 'genre_ids', None),
        director_ids=getattr(payload, 'director_ids', None),
        star_ids=getattr(payload, 'star_ids', None),
        genre_names=getattr(payload, 'genre_names', None),
        director_names=getattr(payload, 'director_names', None),
        star_names=getattr(payload, 'star_names', None),
    )

    await sync_associations(
        db,
        movie.id,
        movie_genres,
        movie_directors,
        movie_stars,
        genres=related.get('genres'),
        directors=related.get('directors'),
        stars=related.get('stars'),
    )

    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return movie


async def update_movie(
    db: AsyncSession,
    movie_id: int,
    payload,
    *,
    MovieModel,
    GenreModel,
    DirectorModel,
    StarModel,
    movie_genres,
    movie_directors,
    movie_stars,
):
    """Update movie fields and associations. Raises ValueError if movie not found or on invalid ids."""
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise ValueError("Movie not found")

    for field in ("name", "year", "time", "imdb", "votes", "description", "price", "certification_id"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(movie, field, val)

    update_genres = (
        getattr(payload, 'genre_ids', None) is not None
        or getattr(payload, 'genre_names', None) is not None
    )
    update_directors = (
        getattr(payload, 'director_ids', None) is not None
        or getattr(payload, 'director_names', None) is not None
    )
    update_stars = (
        getattr(payload, 'star_ids', None) is not None
        or getattr(payload, 'star_names', None) is not None
    )

    if update_genres or update_directors or update_stars:
        related = await prepare_related(
            db,
            GenreModel=GenreModel if update_genres else None,
            DirectorModel=DirectorModel if update_directors else None,
            StarModel=StarModel if update_stars else None,
            genre_ids=getattr(payload, 'genre_ids', None),
            director_ids=getattr(payload, 'director_ids', None),
            star_ids=getattr(payload, 'star_ids', None),
            genre_names=getattr(payload, 'genre_names', None),
            director_names=getattr(payload, 'director_names', None),
            star_names=getattr(payload, 'star_names', None),
        )

        await sync_associations(
            db,
            movie.id,
            movie_genres,
            movie_directors,
            movie_stars,
            genres=related.get('genres') if update_genres else None,
            directors=related.get('directors') if update_directors else None,
            stars=related.get('stars') if update_stars else None,
        )

    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return movie
