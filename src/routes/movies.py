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
    UserModel,
)
from database.models.movies import movie_genres, movie_directors, movie_stars, movie_favorites
from schemas.movies import MovieSummarySchema, GenreSchema, MovieListResponseSchema
from security.deps import require_moderator, get_current_user, get_optional_current_user
from pydantic import BaseModel
from services import movies_service
from fastapi import Body

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


@router.get("/movies/", response_model=MovieListResponseSchema, status_code=status.HTTP_200_OK)
async def list_movies(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    q: str | None = Query(None, description="Search query for title or description"),
    genre_id: int | None = Query(None, description="Filter by genre id"),
    director_id: int | None = Query(None, description="Filter by director id"),
    director_name: str | None = Query(None, description="Filter by director name"),
    star_id: int | None = Query(None, description="Filter by star id"),
    star_name: str | None = Query(None, description="Filter by star name"),
    year: int | None = Query(None, description="Filter by release year"),
    min_imdb: float | None = Query(None, description="Minimum IMDB rating"),
    price_min: float | None = Query(None, description="Minimum price"),
    price_max: float | None = Query(None, description="Maximum price"),
    favorites_only: bool = Query(False, description="If true, return only current user's favorites"),
    sort_by: str = Query("id", description="Sort by: id, price, year, imdb, votes"),
    order: str = Query("asc", description="Sort order: asc or desc"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_current_user),
):
    offset = (page - 1) * size
    # base select
    stmt = select(MovieModel).options(joinedload(MovieModel.genres))

    # filters
    if q:
        stmt = stmt.where(
            MovieModel.name.ilike(f"%{q}%") | MovieModel.description.ilike(f"%{q}%")
        )
    if genre_id:
        stmt = stmt.join(movie_genres).where(movie_genres.c.genre_id == genre_id)
    if director_id:
        stmt = stmt.join(movie_directors).where(movie_directors.c.director_id == director_id)
    if director_name:
        stmt = stmt.join(movie_directors).join(DirectorModel).where(DirectorModel.name.ilike(f"%{director_name}%"))
    if star_id:
        stmt = stmt.join(movie_stars).where(movie_stars.c.star_id == star_id)
    if star_name:
        stmt = stmt.join(movie_stars).join(StarModel).where(StarModel.name.ilike(f"%{star_name}%"))
    if year:
        stmt = stmt.where(MovieModel.year == year)
    if min_imdb:
        stmt = stmt.where(MovieModel.imdb >= min_imdb)
    if price_min is not None:
        stmt = stmt.where(MovieModel.price >= price_min)
    if price_max is not None:
        stmt = stmt.where(MovieModel.price <= price_max)

    if favorites_only:
        if not current_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required for favorites_only")
        stmt = stmt.join(movie_favorites).where(movie_favorites.c.user_id == current_user.id)

    # total count (distinct movies)
    count_stmt = select(func.count(func.distinct(MovieModel.id)))
    # apply same joins/where; easiest is to recreate filters on count_stmt
    if q:
        count_stmt = count_stmt.select_from(MovieModel).where(
            MovieModel.name.ilike(f"%{q}%") | MovieModel.description.ilike(f"%{q}%")
        )
    else:
        count_stmt = count_stmt.select_from(MovieModel)

    # apply joins/filters for count
    if genre_id:
        count_stmt = count_stmt.join(movie_genres).where(movie_genres.c.genre_id == genre_id)
    if director_id:
        count_stmt = count_stmt.join(movie_directors).where(movie_directors.c.director_id == director_id)
    if director_name:
        count_stmt = count_stmt.join(movie_directors).join(DirectorModel).where(DirectorModel.name.ilike(f"%{director_name}%"))
    if star_id:
        count_stmt = count_stmt.join(movie_stars).where(movie_stars.c.star_id == star_id)
    if star_name:
        count_stmt = count_stmt.join(movie_stars).join(StarModel).where(StarModel.name.ilike(f"%{star_name}%"))
    if year:
        count_stmt = count_stmt.where(MovieModel.year == year)
    if min_imdb:
        count_stmt = count_stmt.where(MovieModel.imdb >= min_imdb)
    if price_min is not None:
        count_stmt = count_stmt.where(MovieModel.price >= price_min)
    if price_max is not None:
        count_stmt = count_stmt.where(MovieModel.price <= price_max)
    if favorites_only:
        count_stmt = count_stmt.join(movie_favorites).where(movie_favorites.c.user_id == current_user.id)

    # sorting
    sort_col = getattr(MovieModel, sort_by, None)
    if sort_col is None:
        sort_col = MovieModel.id
    if order.lower() == "desc":
        stmt = stmt.order_by(sort_col.desc())
    else:
        stmt = stmt.order_by(sort_col.asc())

    stmt = stmt.offset(offset).limit(size)
    result = await db.execute(stmt)
    movies = result.unique().scalars().all()

    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0

    return {"total": total, "items": [MovieSummarySchema.model_validate(m) for m in movies]}


@router.post("/movies/", status_code=status.HTTP_201_CREATED)
async def create_movie(
    payload: MovieCreateSchema = Body(..., examples={
        "default": {
            "summary": "Create example",
            "value": {
                "name": "New Movie",
                "year": 2023,
                "time": 120,
                "imdb": 7.5,
                "votes": 1000,
                "description": "A new film",
                "price": 4.99,
                "certification_id": 1,
                "genre_names": ["Action", "Thriller"],
                "director_names": ["Famous Director"],
                "star_names": ["Star A", "Star B"]
            }
        }
    }),
    db: AsyncSession = Depends(get_db),
    _moderator=Depends(require_moderator),
):
    try:
        movie = await movies_service.create_movie(
            db,
            payload,
            MovieModel=MovieModel,
            GenreModel=GenreModel,
            DirectorModel=DirectorModel,
            StarModel=StarModel,
            CertificationModel=CertificationModel,
            movie_genres=movie_genres,
            movie_directors=movie_directors,
            movie_stars=movie_stars,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"id": movie.id, "uuid": movie.uuid}


@router.patch("/movies/{movie_id}/", status_code=status.HTTP_200_OK)
async def update_movie(
    movie_id: int,
    payload: MovieUpdateSchema = Body(..., examples={
        "default": {
            "summary": "Partial update example",
            "value": {"genre_names": ["AddedG"], "director_names": ["AddedDir"]}
        }
    }),
    db: AsyncSession = Depends(get_db),
    _moderator=Depends(require_moderator),
):
    try:
        movie = await movies_service.update_movie(
            db,
            movie_id,
            payload,
            MovieModel=MovieModel,
            GenreModel=GenreModel,
            DirectorModel=DirectorModel,
            StarModel=StarModel,
            movie_genres=movie_genres,
            movie_directors=movie_directors,
            movie_stars=movie_stars,
        )
    except ValueError as e:
        msg = str(e)
        if msg == "Movie not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
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


@router.post("/movies/{movie_id}/favorite/", status_code=status.HTTP_201_CREATED)
async def add_favorite(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    # check existing
    res = await db.execute(select(movie_favorites).where(movie_favorites.c.movie_id == movie_id, movie_favorites.c.user_id == current_user.id))
    if res.first():
        return {"favorited": True}
    await db.execute(movie_favorites.insert().values(movie_id=movie_id, user_id=current_user.id))
    await db.commit()
    return {"favorited": True}


@router.delete("/movies/{movie_id}/favorite/", status_code=status.HTTP_200_OK)
async def remove_favorite(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await db.execute(movie_favorites.delete().where(movie_favorites.c.movie_id == movie_id, movie_favorites.c.user_id == current_user.id))
    await db.commit()
    return {"favorited": False}


@router.get("/movies/favorites/", response_model=List[MovieSummarySchema], status_code=status.HTTP_200_OK)
async def list_favorites(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    offset = (page - 1) * size
    stmt = select(MovieModel).join(movie_favorites).where(movie_favorites.c.user_id == current_user.id).offset(offset).limit(size)
    res = await db.execute(stmt)
    movies = res.unique().scalars().all()
    return [MovieSummarySchema.model_validate(m) for m in movies]


@router.get("/genres/", response_model=List[GenreSchema], status_code=status.HTTP_200_OK)
async def list_genres(db: AsyncSession = Depends(get_db)):
    # Return genres (no counts to keep it simple)
    stmt = select(GenreModel)
    result = await db.execute(stmt)
    genres = result.scalars().all()
    return [GenreSchema.model_validate(g) for g in genres]
