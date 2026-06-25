# System context

Single-host deployment. The browser talks to nginx; nginx serves the SPA from `dist/`, proxies `/api/` to the FastAPI app on `127.0.0.1:5001`, and `alias`-serves `/covers/` directly off disk. The app uses an async SQLAlchemy session per request against SQLite (WAL mode) in dev/prod, or PostgreSQL via a `DATABASE_URL` swap.

```mermaid
flowchart LR
    Browser["Browser<br/>(Vue 3 SPA)"]
    subgraph host["Single host (Ubuntu 24.04)"]
        Nginx["nginx<br/>TLS · static SPA · /covers alias · rate limit on /auth/login"]
        subgraph systemd["systemd: linkgarden.service"]
            Gunicorn["gunicorn<br/>uvicorn.workers.UvicornWorker (w=2)"]
            App["FastAPI app<br/>app.asgi:app"]
            Gunicorn --> App
        end
        DB[("SQLite (WAL)<br/>aiosqlite<br/>linkgarden.db")]
        FS[("Static dir<br/>src/app/static/covers/<card_id>.<ext>")]
    end

    Browser -- "HTTPS" --> Nginx
    Nginx -- "/" --> Browser
    Nginx -- "GET /covers/* (alias)" --> FS
    Nginx -- "proxy_pass /api/" --> Gunicorn
    App -- "async session per request" --> DB
    App -- "atomic write / unlink siblings" --> FS

    classDef ext fill:#0b1220,stroke:#94a3b8,color:#e2e8f0;
    class Browser ext;
```

## Request shapes

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant N as nginx
    participant G as gunicorn+uvicorn
    participant A as FastAPI app
    participant D as SQLite

    B->>N: GET /api/v1/cards
    N->>G: proxy_pass http://127.0.0.1:5001
    G->>A: ASGI request
    A->>D: SELECT cards WHERE archived=false ORDER BY created_at DESC
    D-->>A: rows
    A-->>G: 200 JSON list[CardListItem]
    G-->>N: 200
    N-->>B: 200 (HTTPS)

    B->>N: POST /api/v1/auth/login (rate-limited 10r/m)
    N->>G: proxy_pass
    G->>A: LoginRequest
    A->>D: SELECT user WHERE username=:u
    A-->>G: 200 TokenResponse (JWT HS256, 12h TTL)
    G-->>N: 200
    N-->>B: 200

    B->>N: POST /api/v1/covers (multipart, Bearer)
    N->>G: client_max_body_size 6m
    G->>A: Form(card_id) + UploadFile
    A->>A: MIME sniff · size · Pillow.verify() · dims
    A->>+D: BEGIN
    A->>D: UPDATE cards SET cover=...
    A->>A: atomic write .tmp + os.replace; unlink old-ext siblings
    A->>-D: COMMIT
    A-->>G: 201 CoverUploadResponse
```

## Legacy `/api/*` shim

```mermaid
flowchart LR
    Client["Old client / bookmark"] -- "GET /api/cards" --> App["FastAPI app"]
    App -- "catch-all<br/>excludes v1/ and health" --> Shim["legacy_redirect()"]
    Shim -- "308 Permanent Redirect<br/>+ structlog WARN" --> Client
    Client -- "GET /api/v1/cards" --> App
```
