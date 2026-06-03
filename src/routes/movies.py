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


class MovieUpdateSchema(MovieCreateSchema):
    pass


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
    for k, v in payload.model_dump().items():
        setattr(movie, k, v)
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
