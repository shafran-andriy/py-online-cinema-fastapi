import uuid
from sqlalchemy import (
    Table, Column, Integer, String, ForeignKey, Float, UniqueConstraint, DECIMAL
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# Association tables
movie_genres = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id"), primary_key=True),
)

movie_directors = Table(
    "movie_directors",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("director_id", ForeignKey("directors.id"), primary_key=True),
)

movie_stars = Table(
    "movie_stars",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("star_id", ForeignKey("stars.id"), primary_key=True),
)

# User favorites association (user can favorite many movies)
movie_favorites = Table(
    "movie_favorites",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class GenreModel(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    movies = relationship("MovieModel", secondary=movie_genres, back_populates="genres")

    def __repr__(self):
        return f"<Genre(id={self.id}, name={self.name})>"


class StarModel(Base):
    __tablename__ = "stars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    movies = relationship("MovieModel", secondary=movie_stars, back_populates="stars")

    def __repr__(self):
        return f"<Star(id={self.id}, name={self.name})>"


class DirectorModel(Base):
    __tablename__ = "directors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    movies = relationship("MovieModel", secondary=movie_directors, back_populates="directors")

    def __repr__(self):
        return f"<Director(id={self.id}, name={self.name})>"


class CertificationModel(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    movies = relationship("MovieModel", back_populates="certification")

    def __repr__(self):
        return f"<Certification(id={self.id}, name={self.name})>"


class MovieModel(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)  # duration in minutes
    imdb: Mapped[float] = mapped_column(Float, nullable=False)
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_score: Mapped[float] = mapped_column(Float, nullable=True)
    gross: Mapped[float] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    price: Mapped[float] = mapped_column(DECIMAL(10, 2))

    certification_id: Mapped[int] = mapped_column(ForeignKey("certifications.id"), nullable=False)
    certification = relationship("CertificationModel", back_populates="movies")

    genres = relationship("GenreModel", secondary=movie_genres, back_populates="movies")
    directors = relationship("DirectorModel", secondary=movie_directors, back_populates="movies")
    stars = relationship("StarModel", secondary=movie_stars, back_populates="movies")

    __table_args__ = (UniqueConstraint("name", "year", "time", name="uq_movie_name_year_time"),)

    def __repr__(self):
        return f"<Movie(id={self.id}, name={self.name}, year={self.year})>"
