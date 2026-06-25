# Backend modules

Feature-modular vertical slices on top of `core/` plumbing. Routers wire DI and call services; services own logic and call repositories; repositories own all SQL. The pattern is uniform across `auth`, `cards`, `covers`, `tags`, and `health`.

## Tree

```mermaid
flowchart TB
    classDef router fill:#1e293b,stroke:#38bdf8,color:#e0f2fe;
    classDef service fill:#0f172a,stroke:#a78bfa,color:#ede9fe;
    classDef repo fill:#0c0a09,stroke:#34d399,color:#d1fae5;
    classDef core fill:#111827,stroke:#fbbf24,color:#fef3c7;
    classDef ext fill:#020617,stroke:#94a3b8,color:#cbd5e1;

    Main["app.main.create_app()<br/>lifespan · CORS (dev only) · exception handlers<br/>mounts: GET /api/health · /api/v1/* · legacy 308 catch-all"]:::core
    Asgi["app.asgi:app<br/>gunicorn target"]:::core

    subgraph CORE["app.core"]
        Config["config.Settings"]:::core
        DB["db<br/>create_async_engine · async_sessionmaker · get_session"]:::core
        Pragmas["pragmas<br/>WAL · FK=ON · busy_timeout"]:::core
        Security["security<br/>bcrypt · encode/decode_jwt"]:::core
        Errors["errors<br/>AppError · ErrorEnvelope · register_handlers"]:::core
        Logging["logging<br/>structlog + request_id"]:::core
        Types["types.GUID"]:::core
    end

    subgraph SVC["app.services"]
        Markdown["markdown.render_markdown<br/>md-it-py + plugins → nh3"]:::service
    end

    subgraph FH["features.health"]
        HealthR["routes.GET /health"]:::router
    end

    subgraph FA["features.auth"]
        AuthM["models.User"]:::repo
        AuthS["schemas.LoginRequest · TokenResponse · UserRead"]:::service
        AuthRepo["repo.UserRepository"]:::repo
        AuthSvc["service.authenticate · mint_token"]:::service
        AuthDeps["deps.CurrentUser · AdminUser"]:::service
        AuthR["routes.POST /auth/login · GET /auth/me"]:::router
    end

    subgraph FC["features.cards"]
        CardsM["models.Card"]:::repo
        CardsS["schemas.CardCreate · CardUpdate · CardArchive · CardListItem · CardRead · CardDetail · CardListQuery"]:::service
        CardsSlug["slug.slugify · unique_slug"]:::service
        CardsRepo["repo.CardRepository"]:::repo
        CardsSvc["service.list · get_detail · publish · update · set_archive · delete"]:::service
        CardsR["routes.GET /cards · GET /cards/{slug}<br/>POST · PUT · PATCH /archive · DELETE"]:::router
    end

    subgraph FCo["features.covers"]
        CoversS["schemas.CoverUploadResponse"]:::service
        CoversSvc["service.upload_cover<br/>MIME sniff · Pillow.verify() · atomic write"]:::service
        CoversR["routes.POST /covers"]:::router
    end

    subgraph FT["features.tags"]
        TagsRepo["repo.list_distinct_tags"]:::repo
        TagsR["routes.GET /tags"]:::router
    end

    DBlite[("SQLite WAL · aiosqlite<br/>(or asyncpg via DSN swap)")]:::ext
    FS[("Static dir<br/>covers/<card_id>.<ext>")]:::ext

    Asgi --> Main
    Main --> HealthR
    Main --> AuthR
    Main --> CardsR
    Main --> CoversR
    Main --> TagsR
    Main --> Errors
    Main --> Config
    Main --> DB

    AuthR --> AuthDeps
    AuthR --> AuthSvc
    AuthSvc --> AuthRepo
    AuthRepo --> AuthM
    AuthDeps --> Security
    AuthDeps --> AuthRepo

    CardsR --> AuthDeps
    CardsR --> CardsSvc
    CardsSvc --> CardsRepo
    CardsSvc --> CardsSlug
    CardsSvc --> Markdown
    CardsRepo --> CardsM

    CoversR --> AuthDeps
    CoversR --> CoversSvc
    CoversSvc --> CardsRepo
    CoversSvc --> Config
    CoversSvc -.-> FS

    TagsR --> TagsRepo
    TagsRepo --> CardsM

    AuthM --- DB
    CardsM --- DB
    DB --- DBlite
    DB --- Pragmas
```

## Layers and rules

| Layer | Owns | Imports allowed | Forbidden |
|---|---|---|---|
| `routes.py` | HTTP wiring, DI, schema validation | `service.py`, `deps.py`, `schemas.py` | SQL, business logic, ORM models |
| `service.py` | Business logic, orchestration, error raising | `repo.py`, `services/*`, `core/*`, `schemas.py` | SQL, FastAPI imports |
| `repo.py` | All SQL, ORM access | `models.py`, `sqlalchemy` | Pydantic, FastAPI, business rules |
| `models.py` | ORM tables + relationships | `core.db`, `core.types`, `sqlalchemy` | Pydantic, services |
| `schemas.py` | Pydantic request/response shapes | `pydantic`, type aliases | ORM, SQL |
| `core/*` | Cross-cutting plumbing | each other (acyclic) | features |
| `services/*` | Pure helpers (e.g. markdown) | stdlib + libs | features, DB, FastAPI |

Routers cap at ~30 LOC each. Anything heavier moves into the service.

## Write path (cards.publish)

```mermaid
sequenceDiagram
    autonumber
    participant R as routes.cards.publish
    participant Dep as deps.AdminUser
    participant Svc as service.publish
    participant Slug as slug.unique_slug
    participant MD as services.markdown
    participant Repo as repo.CardRepository
    participant DB as SQLite (async)

    R->>Dep: resolve admin
    Dep-->>R: User
    R->>Svc: publish(payload, author)
    Svc->>Slug: unique_slug(session, base)
    Slug->>Repo: slug_exists(base, exclude_id=None)
    Repo->>DB: SELECT 1 FROM cards WHERE slug=:s AND archived=false
    DB-->>Repo: 0
    Repo-->>Slug: false
    Slug-->>Svc: "<final-slug>"
    Svc->>MD: render_markdown(body) (when category='local')
    MD-->>Svc: sanitized HTML
    Svc->>Repo: insert(new_card)
    Repo->>DB: INSERT INTO cards ...
    DB-->>Repo: ok
    Svc->>Repo: get_by_id(new_id)   # re-SELECT, expire_on_commit=False safe
    Repo->>DB: SELECT * FROM cards WHERE id=:id
    DB-->>Repo: fresh row
    Repo-->>Svc: Card
    Svc-->>R: CardDetail
    R-->>R: 201 Created
```

## Migration

```mermaid
flowchart LR
    Op["operator"] -->|"alembic upgrade head"| Alembic["env.py<br/>connection.run_sync<br/>render_as_batch=True (SQLite)"]
    Alembic -->|"imports app.features.*.models"| Meta["Base.metadata"]
    Alembic -->|"0001_initial"| Tables["users · cards"]
    Alembic -->|"0002_seed_admin (data migration)"| Seed["INSERT admin<br/>iff users count == 0"]
    Op -->|"uv run python -m scripts.migrate_from_json"| Importer["legacy importer<br/>idempotent on slug"]
    Importer --> Tables
```
