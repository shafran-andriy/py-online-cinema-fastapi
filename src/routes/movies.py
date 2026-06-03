from typing import List
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, attributes

from database import (
    get_db,
    MovieModel,
    GenreModel,
    CertificationModel,
    DirectorModel,
    StarModel,
)
from database.models.movies import movie_genres, movie_directors, movie_stars
from schemas.movies import MovieSummarySchema, GenreSchema
from security.deps import require_moderator
from pydantic import BaseModel

router = APIRouter()


class MovieCreateSchema(BaseModel):
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    description: str
    price: float
    certification_id: int
    genre_ids: list[int] | None = None
    director_ids: list[int] | None = None
    star_ids: list[int] | None = None
    # allow creating/attaching by names inline
    genre_names: list[str] | None = None
    director_names: list[str] | None = None
    star_names: list[str] | None = None


class MovieUpdateSchema(BaseModel):
    name: str | None = None
    year: int | None = None
    time: int | None = None
    imdb: float | None = None
    votes: int | None = None
    description: str | None = None
    price: float | None = None
    certification_id: int | None = None
    genre_ids: list[int] | None = None
    director_ids: list[int] | None = None
    star_ids: list[int] | None = None
    # allow names on update as well
    genre_names: list[str] | None = None
    director_names: list[str] | None = None
    star_names: list[str] | None = None


@router.get("/movies/", response_model=List[MovieSummarySchema], status_code=status.HTTP_200_OK)
async def list_movies(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * size
    stmt = select(MovieModel).options(joinedload(MovieModel.genres)).offset(offset).limit(size)
    result = await db.execute(stmt)
    movies = result.unique().scalars().all()
    return [MovieSummarySchema.model_validate(m) for m in movies]


@router.post("/movies/", status_code=status.HTTP_201_CREATED)
async def create_movie(
    payload: MovieCreateSchema,
    db: AsyncSession = Depends(get_db),
    _moderator=Depends(require_moderator),
):
    # validate certification exists
    cert = await db.get(CertificationModel, payload.certification_id)
    if not cert:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid certification_id")

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

    # add movie to session early to avoid SAWarning when associating new related objects
    db.add(movie)
    # flush so movie has a PK and relationship assignments won't trigger lazy loads
    await db.flush()

    # attach relationships if provided (ids)
    genres_list: list = []
    if getattr(payload, 'genre_ids', None):
        stmt = select(GenreModel).where(GenreModel.id.in_(payload.genre_ids))
        res = await db.execute(stmt)
        genres = res.scalars().all()
        if len(genres) != len(set(payload.genre_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more genre_ids invalid")
        genres_list.extend(genres)

    directors_list: list = []
    if getattr(payload, 'director_ids', None):
        stmt = select(DirectorModel).where(DirectorModel.id.in_(payload.director_ids))
        res = await db.execute(stmt)
        directors = res.scalars().all()
        if len(directors) != len(set(payload.director_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more director_ids invalid")
        directors_list.extend(directors)

    stars_list: list = []
    if getattr(payload, 'star_ids', None):
        stmt = select(StarModel).where(StarModel.id.in_(payload.star_ids))
        res = await db.execute(stmt)
        stars = res.scalars().all()
        if len(stars) != len(set(payload.star_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more star_ids invalid")
        stars_list.extend(stars)

    # attach or create by names if provided
    # genre names
    if getattr(payload, 'genre_names', None):
        names = [n.strip() for n in payload.genre_names if n and n.strip()]
        if names:
            stmt = select(GenreModel).where(GenreModel.name.in_(names))
            res = await db.execute(stmt)
            existing = res.scalars().all()
            existing_names = {g.name for g in existing}
            missing_names = [n for n in names if n not in existing_names]
            new_objs = [GenreModel(name=n) for n in missing_names]
            if new_objs:
                db.add_all(new_objs)
                await db.flush()
            genres_list.extend(existing + new_objs)

    if genres_list:
        for g in genres_list:
            await db.execute(movie_genres.insert().values(movie_id=movie.id, genre_id=g.id))

    # director names
    if getattr(payload, 'director_names', None):
        names = [n.strip() for n in payload.director_names if n and n.strip()]
        if names:
            stmt = select(DirectorModel).where(DirectorModel.name.in_(names))
            res = await db.execute(stmt)
            existing = res.scalars().all()
            existing_names = {d.name for d in existing}
            missing_names = [n for n in names if n not in existing_names]
            new_objs = [DirectorModel(name=n) for n in missing_names]
            if new_objs:
                db.add_all(new_objs)
                await db.flush()
            directors_combined = directors_list + existing + new_objs
            # deduplicate by name
            seen = set(); dedup = []
            for d in directors_combined:
                if d.name not in seen:
                    dedup.append(d); seen.add(d.name)
            for d in dedup:
                await db.execute(movie_directors.insert().values(movie_id=movie.id, director_id=d.id))

    # star names
    if getattr(payload, 'star_names', None):
        names = [n.strip() for n in payload.star_names if n and n.strip()]
        if names:
            stmt = select(StarModel).where(StarModel.name.in_(names))
            res = await db.execute(stmt)
            existing = res.scalars().all()
            existing_names = {s.name for s in existing}
            missing_names = [n for n in names if n not in existing_names]
            new_objs = [StarModel(name=n) for n in missing_names]
            if new_objs:
                db.add_all(new_objs)
                await db.flush()
            stars_combined = stars_list + existing + new_objs
            seen = set(); dedup = []
            for s in stars_combined:
                if s.name not in seen:
                    dedup.append(s); seen.add(s.name)
            for s in dedup:
                await db.execute(movie_stars.insert().values(movie_id=movie.id, star_id=s.id))

    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return {"id": movie.id, "uuid": movie.uuid}


@router.patch("/movies/{movie_id}/", status_code=status.HTTP_200_OK)
async def update_movie(
    movie_id: int,
    payload: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
    _moderator=Depends(require_moderator),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    # simple field updates
    for field in ("name", "year", "time", "imdb", "votes", "description", "price", "certification_id"):
        val = getattr(payload, field)
        if val is not None:
            setattr(movie, field, val)

    # prepare new relationship lists
    # genres
    if getattr(payload, 'genre_ids', None) is not None or getattr(payload, 'genre_names', None) is not None:
        genres_list = []
        if getattr(payload, 'genre_ids', None):
            stmt = select(GenreModel).where(GenreModel.id.in_(payload.genre_ids))
            res = await db.execute(stmt)
            genres = res.scalars().all()
            if len(genres) != len(set(payload.genre_ids)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more genre_ids invalid")
            genres_list.extend(genres)
        if getattr(payload, 'genre_names', None):
            names = [n.strip() for n in payload.genre_names if n and n.strip()]
            if names:
                stmt = select(GenreModel).where(GenreModel.name.in_(names))
                res = await db.execute(stmt)
                existing = res.scalars().all()
                existing_names = {g.name for g in existing}
                missing_names = [n for n in names if n not in existing_names]
                new_objs = [GenreModel(name=n) for n in missing_names]
                if new_objs:
                    db.add_all(new_objs)
                    await db.flush()
                genres_list.extend(existing + new_objs)
        attributes.set_committed_value(movie, 'genres', genres_list)

    # directors
    if getattr(payload, 'director_ids', None) is not None or getattr(payload, 'director_names', None) is not None:
        directors_list = []
        if getattr(payload, 'director_ids', None):
            stmt = select(DirectorModel).where(DirectorModel.id.in_(payload.director_ids))
            res = await db.execute(stmt)
            directors = res.scalars().all()
            if len(directors) != len(set(payload.director_ids)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more director_ids invalid")
            directors_list.extend(directors)
        if getattr(payload, 'director_names', None):
            names = [n.strip() for n in payload.director_names if n and n.strip()]
            if names:
                stmt = select(DirectorModel).where(DirectorModel.name.in_(names))
                res = await db.execute(stmt)
                existing = res.scalars().all()
                existing_names = {d.name for d in existing}
                missing_names = [n for n in names if n not in existing_names]
                new_objs = [DirectorModel(name=n) for n in missing_names]
                if new_objs:
                    db.add_all(new_objs)
                    await db.flush()
                directors_list.extend(existing + new_objs)
        attributes.set_committed_value(movie, 'directors', directors_list)

    # stars
    if getattr(payload, 'star_ids', None) is not None or getattr(payload, 'star_names', None) is not None:
        stars_list = []
        if getattr(payload, 'star_ids', None):
            stmt = select(StarModel).where(StarModel.id.in_(payload.star_ids))
            res = await db.execute(stmt)
            stars = res.scalars().all()
            if len(stars) != len(set(payload.star_ids)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more star_ids invalid")
            stars_list.extend(stars)
        if getattr(payload, 'star_names', None):
            names = [n.strip() for n in payload.star_names if n and n.strip()]
            if names:
                stmt = select(StarModel).where(StarModel.name.in_(names))
                res = await db.execute(stmt)
                existing = res.scalars().all()
                existing_names = {s.name for s in existing}
                missing_names = [n for n in names if n not in existing_names]
                new_objs = [StarModel(name=n) for n in missing_names]
                if new_objs:
                    db.add_all(new_objs)
                    await db.flush()
                stars_list.extend(existing + new_objs)
        attributes.set_committed_value(movie, 'stars', stars_list)

    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return {"id": movie.id}


@router.delete("/movies/{movie_id}/", status_code=status.HTTP_200_OK)
async def delete_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    _moderator=Depends(require_moderator),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    await db.delete(movie)
    await db.commit()
    return {"deleted": True}


@router.get("/genres/", response_model=List[GenreSchema], status_code=status.HTTP_200_OK)
async def list_genres(db: AsyncSession = Depends(get_db)):
    # Return genres (no counts to keep it simple)
    stmt = select(GenreModel)
    result = await db.execute(stmt)
    genres = result.scalars().all()
    return [GenreSchema.model_validate(g) for g in genres]
