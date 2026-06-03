from typing import List
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from database import (
    get_db,
    MovieModel,
    GenreModel,
    CertificationModel,
    DirectorModel,
    StarModel,
)
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

    # attach relationships if provided
    if payload.genre_ids:
        stmt = select(GenreModel).where(GenreModel.id.in_(payload.genre_ids))
        res = await db.execute(stmt)
        genres = res.scalars().all()
        if len(genres) != len(set(payload.genre_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more genre_ids invalid")
        movie.genres = genres

    if payload.director_ids:
        stmt = select(DirectorModel).where(DirectorModel.id.in_(payload.director_ids))
        res = await db.execute(stmt)
        directors = res.scalars().all()
        if len(directors) != len(set(payload.director_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more director_ids invalid")
        movie.directors = directors

    if payload.star_ids:
        stmt = select(StarModel).where(StarModel.id.in_(payload.star_ids))
        res = await db.execute(stmt)
        stars = res.scalars().all()
        if len(stars) != len(set(payload.star_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more star_ids invalid")
        movie.stars = stars

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

    # update relationships
    if payload.genre_ids is not None:
        stmt = select(GenreModel).where(GenreModel.id.in_(payload.genre_ids))
        res = await db.execute(stmt)
        genres = res.scalars().all()
        if len(genres) != len(set(payload.genre_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more genre_ids invalid")
        movie.genres = genres

    if payload.director_ids is not None:
        stmt = select(DirectorModel).where(DirectorModel.id.in_(payload.director_ids))
        res = await db.execute(stmt)
        directors = res.scalars().all()
        if len(directors) != len(set(payload.director_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more director_ids invalid")
        movie.directors = directors

    if payload.star_ids is not None:
        stmt = select(StarModel).where(StarModel.id.in_(payload.star_ids))
        res = await db.execute(stmt)
        stars = res.scalars().all()
        if len(stars) != len(set(payload.star_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more star_ids invalid")
        movie.stars = stars

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
