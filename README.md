# py-online-cinema-fastapi

An online cinema is a digital platform that allows users to select, watch, and purchase access to movies and other video materials via the internet. These services have become popular due to their convenience, a wide selection of content, and the ability to personalize the user experience.

## Movies API (create / update)

New optional fields supported on movie create and update endpoints:

- genre_names: list[str] - create or attach genres by name inline
- director_names: list[str] - create or attach directors by name inline
- star_names: list[str] - create or attach stars by name inline

Behavior:
- When both ids and names are provided, ids take precedence for existing objects; names will create missing objects if they do not exist.
- Duplicate names are deduplicated before association.

Create example (POST /api/v1/theater/movies/):

{
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

Update example (PATCH /api/v1/theater/movies/{id}/):

{
  "genre_names": ["AddedG"],
  "director_names": ["AddedDir"]
}

These fields are documented in Swagger (FastAPI) and appear in the request schema for the endpoints.

An online cinema is a digital platform that allows users to select, watch, and purchase access to movies and other video materials via the internet. These services have become popular due to their convenience, a wide selection of content, and the ability to personalize the user experience.
