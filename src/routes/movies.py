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

router = APIRouter()


@router.get("/movies/", response_model=List[MovieSummarySchema], status_code=status.HTTP_200_OK)
async def list_movies(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * size
    stmt = select(MovieModel).options(joinedload(MovieModel.genres)).offset(offset).limit(size)
    result = await db.execute(stmt)
    movies = result.scalars().all()
    return [MovieSummarySchema.model_validate(m) for m in movies]


@router.get("/genres/", response_model=List[GenreSchema], status_code=status.HTTP_200_OK)
async def list_genres(db: AsyncSession = Depends(get_db)):
    # Return genres (no counts to keep it simple)
    stmt = select(GenreModel)
    result = await db.execute(stmt)
    genres = result.scalars().all()
    return [GenreSchema.model_validate(g) for g in genres]
