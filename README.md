# Online Cinema — FastAPI Backend

REST API backend for an online cinema platform. Users can browse movies, manage a cart, place orders, and pay via Stripe. Admins manage the movie catalog. Built with FastAPI, PostgreSQL, Redis, Celery, MinIO, and Docker.

## Table of Contents

- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Features & API](#features--api)
- [Quick Start — Local (Poetry)](#quick-start--local-poetry)
- [Quick Start — Docker Compose](#quick-start--docker-compose)
- [Run in PyCharm](#run-in-pycharm)
- [Run in VS Code](#run-in-vs-code)
- [Environment Variables](#environment-variables)
- [Database Migrations](#database-migrations)
- [Running Tests](#running-tests)
- [CI/CD](#cicd)
- [API Documentation](#api-documentation)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.111 |
| Database | PostgreSQL 15 + SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Auth | JWT (access + refresh tokens), bcrypt |
| Task queue | Celery 5 + Redis 7 |
| Email (dev) | MailHog |
| File storage | MinIO (S3-compatible) |
| Payments | Stripe |
| Containerization | Docker + Docker Compose |
| Tests | pytest + pytest-asyncio + httpx + SQLite in-memory |
| CI/CD | GitHub Actions |
| Package manager | Poetry |

---

## Project Structure

```
py-online-cinema-fastapi/
├── src/
│   ├── main.py                  # FastAPI app entry point
│   ├── config/
│   │   ├── settings.py          # Pydantic settings (env-based)
│   │   └── dependencies.py      # DI factories (DB, JWT, email)
│   ├── database/
│   │   ├── __init__.py          # Base + all model exports
│   │   └── models/
│   │       ├── accounts.py      # User, UserGroup, tokens, notifications
│   │       ├── movies.py        # Movie, Genre, Director, Star, Certification
│   │       ├── cart.py          # Cart, CartItem
│   │       ├── orders.py        # Order, OrderItem
│   │       └── payments.py      # Payment, PaymentItem
│   ├── routes/
│   │   ├── accounts.py          # Auth + user management endpoints
│   │   ├── movies.py            # Movie catalog endpoints
│   │   ├── cart.py              # Cart endpoints
│   │   ├── orders.py            # Order endpoints
│   │   ├── payments.py          # Stripe payment endpoints
│   │   ├── profiles.py          # User profile endpoints
│   │   └── docs.py              # Protected /docs + /redoc
│   ├── schemas/                 # Pydantic request/response models
│   ├── services/                # Business logic layer
│   ├── security/                # JWT manager, password hashing, auth deps
│   ├── notifications/           # Email sender (SMTP via MailHog in dev)
│   ├── storages/                # MinIO S3 storage client
│   └── tasks/                   # Celery tasks (cleanup expired tokens)
├── alembic/                     # Alembic migration environment
│   └── versions/
│       └── 666a396d1d88_full_schema.py   # Full 25-table migration
├── tests/                       # pytest test suite (SQLite in-memory)
├── .github/
│   └── workflows/
│       ├── ci.yml               # CI: lint + typecheck + test
│       └── main.yml             # CD: deploy to AWS EC2
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.sample
```

---

## Features & API

All endpoints are prefixed with `/api/v1`.

### Accounts — `/api/v1/accounts`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/register/` | Register new user | — |
| POST | `/activate/` | Activate account via email token | — |
| POST | `/activation/resend/` | Resend activation email | — |
| POST | `/login/` | Login, get access + refresh tokens | — |
| POST | `/logout/` | Invalidate refresh token | Required |
| POST | `/token/refresh/` | Refresh access token | — |
| POST | `/password-reset/request/` | Send password reset email | — |
| POST | `/reset-password/complete/` | Set new password via reset token | — |
| POST | `/change-password/` | Change password (authenticated) | Required |
| GET | `/users/` | List all users | Admin |
| PATCH | `/users/{id}/group/` | Change user group | Admin |
| POST | `/users/{id}/activate/` | Manually activate account | Admin |

### Profiles — `/api/v1/profiles`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/me/` | Get own profile | Required |
| PATCH | `/me/` | Update profile | Required |
| POST | `/me/avatar/` | Upload avatar | Required |

### Movies — `/api/v1`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/movies/` | List movies (filter by genre, year, price, search) | — |
| POST | `/movies/` | Create movie | Moderator |
| PATCH | `/movies/{id}/` | Update movie | Moderator |
| DELETE | `/movies/{id}/` | Delete movie | Moderator |
| GET | `/movies/{id}/` | Movie detail | — |
| POST | `/movies/{id}/favorite/` | Add to favorites | Required |
| DELETE | `/movies/{id}/favorite/` | Remove from favorites | Required |
| GET | `/movies/favorites/` | List my favorites | Required |
| GET | `/genres/` | List all genres with movie count | — |
| POST | `/movies/{id}/like/` | Like a movie | Required |
| POST | `/movies/{id}/dislike/` | Dislike a movie | Required |
| DELETE | `/movies/{id}/like/` | Remove like/dislike | Required |
| POST | `/movies/{id}/rate/` | Rate a movie | Required |
| POST | `/movies/{id}/comments/` | Add comment | Required |
| GET | `/movies/{id}/comments/` | List comments | — |
| POST | `/movies/{id}/comments/{cid}/replies/` | Reply to comment | Required |
| DELETE | `/comments/{cid}/` | Delete comment | Required |

### Cart — `/api/v1/cart`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/` | Get current user's cart | Required |
| POST | `/items/` | Add movie to cart | Required |
| DELETE | `/items/{movie_id}/` | Remove movie from cart | Required |
| DELETE | `/` | Clear cart | Required |

### Orders — `/api/v1/orders`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/` | Create order from cart | Required |
| GET | `/` | List my orders | Required |
| GET | `/{order_id}/` | Get order detail | Required |
| PATCH | `/{order_id}/cancel/` | Cancel order | Required |

### Payments — `/api/v1/payments`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/create-session/` | Create Stripe Checkout session | Required |
| GET | `/success/` | Stripe success redirect | — |
| GET | `/cancel/` | Stripe cancel redirect | — |
| POST | `/webhook/` | Stripe webhook handler | — |
| GET | `/` | List my payments | Required |

### Admin — `/api/v1/admin`

| Method | Path | Description | Auth |
|---|---|---|---|
| GET | `/carts/` | View all users' carts | Moderator |
| GET | `/orders/` | All orders with filters | Moderator |
| GET | `/payments/` | All payments with filters | Moderator |

---

## Quick Start — Local (Poetry)

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation) installed
- PostgreSQL 15 running locally (or via Docker)
- Redis running locally (or via Docker)

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/py-online-cinema-fastapi.git
cd py-online-cinema-fastapi

# 2. Install dependencies
poetry install

# 3. Activate the virtual environment
poetry shell

# 4. Copy environment file and fill in values
cp .env.sample .env
# Edit .env with your local DB credentials, secret keys, etc.

# 5. Run Alembic migrations
alembic upgrade head

# 6. Start the app
PYTHONPATH=src uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.

---

## Quick Start — Docker Compose

### Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine + Docker Compose v2 (Linux)

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/py-online-cinema-fastapi.git
cd py-online-cinema-fastapi

# 2. Copy and configure environment file
cp .env.sample .env
# Edit .env — at minimum set SECRET_KEY_ACCESS, SECRET_KEY_REFRESH, STRIPE_SECRET_KEY

# 3. Build and start all services
docker compose up --build -d

# Services started:
#   db       — PostgreSQL  :5432
#   redis    — Redis        :6379
#   minio    — MinIO S3     :9000 (API), :9001 (Console)
#   mailhog  — MailHog SMTP :1025 (SMTP), :8025 (Web UI)
#   web      — FastAPI app  :8000
#   worker   — Celery worker
#   beat     — Celery beat scheduler

# 4. Run migrations (first time only)
docker compose run --rm web alembic upgrade head

# 5. Stop all services
docker compose down
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |
| MailHog Web UI | http://localhost:8025 |

---

## Run in PyCharm

1. Open the project folder in PyCharm.
2. **Set Python interpreter:**
   `File → Settings → Project → Python Interpreter → Add Interpreter → Poetry Environment`
3. **Configure Run/Debug:**
   `Run → Edit Configurations → + → Python`
   - Module: `uvicorn`
   - Parameters: `src.main:app --host 0.0.0.0 --port 8000 --reload`
   - Working directory: `<project root>`
   - Environment variables: add all from `.env` or set `PYTHONPATH=src`
4. Click **Run** or **Debug**.

To run tests in PyCharm:
- `Run → Edit Configurations → + → pytest`
- Set working directory to project root
- Add `PYTHONPATH=src` and `ENVIRONMENT=testing` to environment variables

---

## Run in VS Code

1. Open the project folder in VS Code.
2. Install the **Python** extension (`ms-python.python`).
3. Select interpreter: `Ctrl+Shift+P → Python: Select Interpreter → Poetry env`
4. Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
      "cwd": "${workspaceFolder}",
      "env": {
        "PYTHONPATH": "${workspaceFolder}/src"
      },
      "envFile": "${workspaceFolder}/.env",
      "jinja": true
    }
  ]
}
```

5. Press **F5** to start debugging.

For tests, create or update `.vscode/settings.json`:

```json
{
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "python.envFile": "${workspaceFolder}/.env",
  "terminal.integrated.env.windows": {
    "PYTHONPATH": "${workspaceFolder}/src",
    "ENVIRONMENT": "testing"
  }
}
```

---

## Environment Variables

Copy `.env.sample` to `.env` and fill in the values:

```dotenv
# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=online_cinema
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/online_cinema

# Redis
REDIS_URL=redis://redis:6379/0

# JWT
SECRET_KEY_ACCESS=<generate: openssl rand -hex 32>
SECRET_KEY_REFRESH=<generate: openssl rand -hex 32>
JWT_SIGNING_ALGORITHM=HS256

# Email (MailHog in development)
EMAIL_HOST=mailhog
EMAIL_PORT=1025
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=False

# MinIO (S3-compatible storage)
MINIO_HOST=minio
MINIO_PORT=9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_STORAGE=theater-storage

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

---

## Database Migrations

Migrations are managed with Alembic. The full schema (25 tables) is in a single initial migration.

```bash
# Apply all migrations
alembic upgrade head

# Roll back the last migration
alembic downgrade -1

# Generate a new migration after model changes
alembic revision --autogenerate -m "describe your change"

# Show migration history
alembic history

# Show current applied revision
alembic current
```

When running via Docker Compose:

```bash
docker compose run --rm web alembic upgrade head
```

---

## Running Tests

Tests use an in-memory SQLite database — no external services required.

```bash
# Run all tests
PYTHONPATH=src ENVIRONMENT=testing poetry run pytest -q

# With verbose output
PYTHONPATH=src ENVIRONMENT=testing poetry run pytest -v

# Run a specific test file
PYTHONPATH=src ENVIRONMENT=testing poetry run pytest tests/test_integration_accounts.py -v

# With coverage report
PYTHONPATH=src ENVIRONMENT=testing poetry run pytest --cov=src --cov-report=term-missing
```

The test suite covers:
- Account registration, activation, login, password reset, change password flows
- Admin user management (list users, change group, manual activation)
- User profile CRUD and avatar upload
- Movie CRUD, filtering, sorting, favorites, likes, comments, ratings
- Cart management (add, remove, clear, duplicate prevention)
- Order creation, listing, cancellation
- Stripe payment sessions, webhooks, payment history
- Admin views of all carts, orders, and payments
- Celery cleanup tasks (expired activation, password reset, refresh tokens)
- End-to-end flows: register → activate → login → cart → order → payment

---

## CI/CD

### Continuous Integration (`.github/workflows/ci.yml`)

Triggered on every push to `main` and `feature/**` branches, and on pull requests to `main`.

- **Lint job:** runs `flake8` on `src/`
- **Type check job:** runs `mypy` on `src/`
- **Test job:** installs dependencies via Poetry, runs `pytest` against SQLite (no external services needed)

### Continuous Deployment (`.github/workflows/main.yml`)

Triggered on push to `main`. Deploys to an AWS EC2 instance via SSH:

1. SSH into EC2 instance
2. `git pull origin main`
3. `docker compose up --build -d`
4. Run Alembic migrations

**Required GitHub Secrets:**

| Secret | Description |
|---|---|
| `EC2_HOST` | Public IP or hostname of the EC2 instance |
| `EC2_USER` | SSH username (e.g. `ubuntu`) |
| `EC2_SSH_KEY` | Private SSH key (PEM format, full content) |

---

## API Documentation

Swagger UI and ReDoc are protected — a valid JWT access token is required to access them.

1. Get a token: `POST /api/v1/accounts/login/`
2. Open `http://localhost:8000/docs`
3. Click **Authorize** and enter `Bearer <your_access_token>`

| URL | Description |
|---|---|
| `GET /docs` | Swagger UI |
| `GET /redoc` | ReDoc |
| `GET /openapi.json` | Raw OpenAPI schema |

---

## Live Demo — AWS EC2

The project is successfully deployed on AWS EC2 and available at:

| Service | URL |
|---|---|
| **Swagger UI** | [http://34.225.57.28:8000/docs](http://34.225.57.28:8000/docs) |
| **API** | [http://34.225.57.28:8000](http://34.225.57.28:8000) |
| **MailHog** (email dev UI) | [http://34.225.57.28:8025](http://34.225.57.28:8025) |
| **MinIO Console** (S3 storage) | [http://34.225.57.28:9001](http://34.225.57.28:9001) |

### Test Accounts

Ready-to-use accounts for exploring all functionality:

| Email | Password | Role | Capabilities |
|---|---|---|---|
| `admin@cinema.com` | `Admin123!` | **Admin** | All endpoints, user management, movie CRUD |
| `user1@cinema.com` | `User123!` | **User** | Browse movies, cart, orders, payments |
| `user2@cinema.com` | `User123!` | **Moderator** | Create/edit/delete movies, view all carts & orders |

**Quick start:**
1. Open [Swagger UI](http://34.225.57.28:8000/docs)
2. Use `POST /api/v1/accounts/login/` with credentials above
3. Copy `access_token` → click **Authorize** → paste `Bearer <token>`
4. Explore all endpoints

See [seed_data.json](seed_data.json) for full test dataset (movies, orders, payments).

---

## Test Dataset

The file [`seed_data.json`](seed_data.json) contains a complete test dataset ready for demo and QA.

### Users (3)

| Email | Password | Role |
|---|---|---|
| `admin@cinema.com` | `Admin123!` | ADMIN |
| `user1@cinema.com` | `User123!` | USER |
| `user2@cinema.com` | `User123!` | MODERATOR |

### Movies (10)

| Title | Year | IMDB | Price | Genres |
|---|---|---|---|---|
| Inception | 2010 | 8.8 | $9.99 | Action, Sci-Fi, Thriller |
| The Shawshank Redemption | 1994 | 9.3 | $7.99 | Drama |
| The Dark Knight | 2008 | 9.0 | $9.99 | Action, Thriller |
| Pulp Fiction | 1994 | 8.9 | $8.99 | Thriller, Drama |
| Interstellar | 2014 | 8.7 | $9.99 | Sci-Fi, Drama |
| The Lion King | 1994 | 8.5 | $6.99 | Animation, Drama |
| Forrest Gump | 1994 | 8.8 | $7.99 | Drama, Romance, Comedy |
| The Matrix | 1999 | 8.7 | $8.99 | Action, Sci-Fi |
| Goodfellas | 1990 | 8.7 | $8.99 | Drama, Thriller |
| The Silence of the Lambs | 1991 | 8.6 | $7.99 | Horror, Thriller, Drama |

### Orders & Payments

| User | Movies | Status | Amount |
|---|---|---|---|
| user1 | Shawshank + Dark Knight | **PAID** | $17.98 |
| user1 | Forrest Gump | PENDING | $7.99 |
| user2 | Pulp Fiction + Goodfellas | **PAID** | $17.98 |
| admin | Interstellar + Lion King | CANCELED | $16.98 |

### Additional Data
- **Cart:** user1 has Inception + The Matrix in cart
- **Ratings:** 7 user ratings (scores 9–10) across different movies
- **Comments:** 3 comments including 1 reply thread
- **Reactions:** 7 likes/dislikes across all users
- **Favorites:** each user has 2–3 favorite movies
