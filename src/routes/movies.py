from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException, Query, UploadFile, File
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from database import (
    get_db,
    MovieModel,
    GenreModel,
    CertificationModel,
    DirectorModel,
    StarModel,
    UserModel,
    MovieLikeModel,
    MovieCommentModel,
    MovieRatingModel,
    NotificationModel,
    NotificationTypeEnum,
)
from database.models.movies import movie_genres, movie_directors, movie_stars, movie_favorites
from schemas.movies import (
    MovieSummarySchema,
    MovieDetailSchema,
    GenreSchema,
    GenreWithCountSchema,
    MovieListResponseSchema,
    MovieCommentSchema,
    MovieCommentCreateSchema,
    MovieRatingCreateSchema,
)
from security.deps import require_moderator, get_current_user, get_optional_current_user
from pydantic import BaseModel
from services import movies_service
from fastapi import Body

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: check if movie was purchased (stub until feature/04-orders merged)
# ---------------------------------------------------------------------------

async def _is_movie_purchased(db: AsyncSession, movie_id: int) -> bool:
    """Returns True if movie appears in any paid order. Stub — always False until OrderItemModel exists."""
    return False


# ---------------------------------------------------------------------------
# Helpers: load movie with all relations
# ---------------------------------------------------------------------------

async def _get_movie_or_404(db: AsyncSession, movie_id: int) -> MovieModel:
    stmt = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.genres),
            selectinload(MovieModel.directors),
            selectinload(MovieModel.stars),
            selectinload(MovieModel.certification),
        )
        .where(MovieModel.id == movie_id)
    )
    result = await db.execute(stmt)
    movie = result.scalars().first()
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    return movie


# ---------------------------------------------------------------------------
# Favorites — must be declared BEFORE /movies/{movie_id}/ to avoid int-parse conflict
# ---------------------------------------------------------------------------

@router.get("/movies/favorites/", response_model=List[MovieSummarySchema], status_code=status.HTTP_200_OK)
async def list_favorites(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    offset = (page - 1) * size
    stmt = (
        select(MovieModel)
        .join(movie_favorites)
        .where(movie_favorites.c.user_id == current_user.id)
        .offset(offset).limit(size)
    )
    res = await db.execute(stmt)
    movies = res.unique().scalars().all()
    return [MovieSummarySchema.model_validate(m) for m in movies]


# ---------------------------------------------------------------------------
# 2.1 Movie Detail
# ---------------------------------------------------------------------------

@router.get("/movies/{movie_id}/", response_model=MovieDetailSchema, status_code=status.HTTP_200_OK)
async def get_movie_detail(movie_id: int, db: AsyncSession = Depends(get_db)):
    movie = await _get_movie_or_404(db, movie_id)

    # avg rating
    avg_stmt = select(func.avg(MovieRatingModel.score)).where(MovieRatingModel.movie_id == movie_id)
    avg_result = await db.execute(avg_stmt)
    avg_rating: Optional[float] = avg_result.scalar()

    # like/dislike counts
    likes_stmt = select(func.count()).where(MovieLikeModel.movie_id == movie_id, MovieLikeModel.is_like == True)
    dislikes_stmt = select(func.count()).where(MovieLikeModel.movie_id == movie_id, MovieLikeModel.is_like == False)
    likes_count = (await db.execute(likes_stmt)).scalar() or 0
    dislikes_count = (await db.execute(dislikes_stmt)).scalar() or 0

    data = MovieDetailSchema.model_validate(movie)
    data.avg_rating = round(avg_rating, 2) if avg_rating is not None else None
    data.likes_count = likes_count
    data.dislikes_count = dislikes_count
    return data


# ---------------------------------------------------------------------------
# Movie list
# ---------------------------------------------------------------------------

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
    stmt = select(MovieModel).options(joinedload(MovieModel.genres))

    if q:
        stmt = stmt.where(MovieModel.name.ilike(f"%{q}%") | MovieModel.description.ilike(f"%{q}%"))
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

    count_stmt = select(func.count(func.distinct(MovieModel.id)))
    if q:
        count_stmt = count_stmt.select_from(MovieModel).where(
            MovieModel.name.ilike(f"%{q}%") | MovieModel.description.ilike(f"%{q}%")
        )
    else:
        count_stmt = count_stmt.select_from(MovieModel)

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
            db, payload,
            MovieModel=MovieModel, GenreModel=GenreModel,
            DirectorModel=DirectorModel, StarModel=StarModel,
            CertificationModel=CertificationModel,
            movie_genres=movie_genres, movie_directors=movie_directors, movie_stars=movie_stars,
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
            db, movie_id, payload,
            MovieModel=MovieModel, GenreModel=GenreModel,
            DirectorModel=DirectorModel, StarModel=StarModel,
            movie_genres=movie_genres, movie_directors=movie_directors, movie_stars=movie_stars,
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
    # 2.7: prevent delete if movie was purchased in a paid order
    if await _is_movie_purchased(db, movie_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a movie that has been purchased",
        )
    await db.delete(movie)
    await db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------

@router.post("/movies/{movie_id}/favorite/", status_code=status.HTTP_201_CREATED)
async def add_favorite(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    res = await db.execute(select(movie_favorites).where(
        movie_favorites.c.movie_id == movie_id, movie_favorites.c.user_id == current_user.id
    ))
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
    await db.execute(movie_favorites.delete().where(
        movie_favorites.c.movie_id == movie_id, movie_favorites.c.user_id == current_user.id
    ))
    await db.commit()
    return {"favorited": False}


# ---------------------------------------------------------------------------
# 2.2 Genre list with movie counts
# ---------------------------------------------------------------------------

@router.get("/genres/", response_model=List[GenreWithCountSchema], status_code=status.HTTP_200_OK)
async def list_genres(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(
            GenreModel.id,
            GenreModel.name,
            func.count(movie_genres.c.movie_id).label("movies_count"),
        )
        .outerjoin(movie_genres, GenreModel.id == movie_genres.c.genre_id)
        .group_by(GenreModel.id, GenreModel.name)
        .order_by(GenreModel.name)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [GenreWithCountSchema(id=r.id, name=r.name, movies_count=r.movies_count) for r in rows]


# ---------------------------------------------------------------------------
# 2.3 Like / Dislike
# ---------------------------------------------------------------------------

@router.post("/movies/{movie_id}/like/", status_code=status.HTTP_200_OK)
async def like_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    # upsert: remove existing reaction then insert like
    await db.execute(
        delete(MovieLikeModel).where(
            MovieLikeModel.movie_id == movie_id,
            MovieLikeModel.user_id == current_user.id,
        )
    )
    db.add(MovieLikeModel(movie_id=movie_id, user_id=current_user.id, is_like=True))
    await db.commit()
    return {"liked": True}


@router.post("/movies/{movie_id}/dislike/", status_code=status.HTTP_200_OK)
async def dislike_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    await db.execute(
        delete(MovieLikeModel).where(
            MovieLikeModel.movie_id == movie_id,
            MovieLikeModel.user_id == current_user.id,
        )
    )
    db.add(MovieLikeModel(movie_id=movie_id, user_id=current_user.id, is_like=False))
    await db.commit()
    return {"disliked": True}


@router.delete("/movies/{movie_id}/like/", status_code=status.HTTP_200_OK)
async def cancel_reaction(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    await db.execute(
        delete(MovieLikeModel).where(
            MovieLikeModel.movie_id == movie_id,
            MovieLikeModel.user_id == current_user.id,
        )
    )
    await db.commit()
    return {"removed": True}


# ---------------------------------------------------------------------------
# 2.4 Comments + Replies
# ---------------------------------------------------------------------------

async def _load_comment_with_replies(db: AsyncSession, comment_id: int) -> MovieCommentModel:
    stmt = (
        select(MovieCommentModel)
        .options(selectinload(MovieCommentModel.replies))
        .where(MovieCommentModel.id == comment_id)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


@router.post("/movies/{movie_id}/comments/", response_model=MovieCommentSchema, status_code=status.HTTP_201_CREATED)
async def add_comment(
    movie_id: int,
    body: MovieCommentCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    comment = MovieCommentModel(movie_id=movie_id, user_id=current_user.id, body=body.body)
    db.add(comment)
    await db.commit()
    loaded = await _load_comment_with_replies(db, comment.id)
    return MovieCommentSchema.model_validate(loaded)


@router.get("/movies/{movie_id}/comments/", response_model=List[MovieCommentSchema], status_code=status.HTTP_200_OK)
async def list_comments(
    movie_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    offset = (page - 1) * size
    # load top-level comments with their replies
    stmt = (
        select(MovieCommentModel)
        .options(selectinload(MovieCommentModel.replies))
        .where(MovieCommentModel.movie_id == movie_id, MovieCommentModel.parent_id == None)
        .order_by(MovieCommentModel.created_at.asc())
        .offset(offset).limit(size)
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()
    return [MovieCommentSchema.model_validate(c) for c in comments]


@router.post("/movies/{movie_id}/comments/{comment_id}/replies/", response_model=MovieCommentSchema, status_code=status.HTTP_201_CREATED)
async def add_reply(
    movie_id: int,
    comment_id: int,
    body: MovieCommentCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    parent = await db.get(MovieCommentModel, comment_id)
    if not parent or parent.movie_id != movie_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    reply = MovieCommentModel(
        movie_id=movie_id,
        user_id=current_user.id,
        parent_id=comment_id,
        body=body.body,
    )
    db.add(reply)
    await db.flush()

    # 2.6: notify original comment's author (skip self-notification)
    if parent.user_id != current_user.id:
        notif = NotificationModel(
            user_id=parent.user_id,
            type=NotificationTypeEnum.REPLY,
            related_id=reply.id,
            message=f"Someone replied to your comment on movie #{movie_id}.",
        )
        db.add(notif)

    await db.commit()
    loaded = await _load_comment_with_replies(db, reply.id)
    return MovieCommentSchema.model_validate(loaded)


@router.delete("/comments/{comment_id}/", status_code=status.HTTP_200_OK)
async def delete_comment(
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    comment = await db.get(MovieCommentModel, comment_id)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    # only owner or moderator/admin may delete
    is_moderator = current_user.group.name in (
        __import__("database").UserGroupEnum.MODERATOR,
        __import__("database").UserGroupEnum.ADMIN,
    )
    if comment.user_id != current_user.id and not is_moderator:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to delete this comment")
    await db.delete(comment)
    await db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# 2.5 10-point Rating
# ---------------------------------------------------------------------------

@router.post("/movies/{movie_id}/rate/", status_code=status.HTTP_200_OK)
async def rate_movie(
    movie_id: int,
    body: MovieRatingCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    movie = await db.get(MovieModel, movie_id)
    if not movie:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    # upsert
    stmt = select(MovieRatingModel).where(
        MovieRatingModel.movie_id == movie_id,
        MovieRatingModel.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    existing = result.scalars().first()
    if existing:
        existing.score = body.score
    else:
        db.add(MovieRatingModel(movie_id=movie_id, user_id=current_user.id, score=body.score))
    await db.commit()
    return {"rated": True, "score": body.score}


@router.delete("/movies/{movie_id}/rate/", status_code=status.HTTP_200_OK)
async def delete_rating(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    await db.execute(
        delete(MovieRatingModel).where(
            MovieRatingModel.movie_id == movie_id,
            MovieRatingModel.user_id == current_user.id,
        )
    )
    await db.commit()
    return {"removed": True}
