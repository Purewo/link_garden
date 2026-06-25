# Frontend modules

Feature-modular slices on top of a shared kit. Views call per-feature `api.ts` wrappers; wrappers call the typed `openapi-fetch` client. Pinia setup stores live next to their feature; only `auth` and `ui` persist via `pinia-plugin-persistedstate`.

## Tree

```mermaid
flowchart TB
    classDef view fill:#1e293b,stroke:#38bdf8,color:#e0f2fe;
    classDef store fill:#0f172a,stroke:#a78bfa,color:#ede9fe;
    classDef api fill:#0c0a09,stroke:#34d399,color:#d1fae5;
    classDef shared fill:#111827,stroke:#fbbf24,color:#fef3c7;
    classDef ext fill:#020617,stroke:#94a3b8,color:#cbd5e1;

    Main["main.ts<br/>createApp(App).use(pinia).use(router).mount('#app')"]:::view
    AppRoot["App.vue<br/>:is='currentLayout' + <router-view/>"]:::view

    subgraph Router["router/"]
        Routes["routes.ts<br/>(aggregated from features)"]:::view
        Guards["guards.ts<br/>setTitle · requireAdmin · redirectIfAuthed"]:::view
        Index["index.ts<br/>createRouter + global beforeEach"]:::view
    end

    subgraph Layouts["layouts/"]
        Public["PublicLayout.vue"]:::view
        Admin["AdminLayout.vue"]:::view
        Blank["BlankLayout.vue"]:::view
    end

    subgraph Shared["shared/"]
        ApiClient["api/client.ts<br/>createClient<paths>({baseUrl:'/api/v1'})"]:::api
        ApiInterc["api/interceptors.ts<br/>Bearer · 401 → 'auth:invalidated'"]:::api
        ApiErr["api/errors.ts<br/>AppError · mapError(envelope)"]:::api
        Schema["api/schema.d.ts (GENERATED)"]:::api
        Composables["composables/<br/>useAsync · useDebounce · useToast<br/>useEnhanceCodeBlocks"]:::shared
        UI["ui/<br/>BaseButton · BaseInput · BaseTextarea<br/>BaseSelect · BaseTagInput · BaseModal<br/>BaseToast · AppSpinner · NotFoundView"]:::shared
        Utils["utils/<br/>slug · date · bytes · invariant"]:::shared
        Types["types/domain.ts<br/>(re-exports from schema.d.ts)"]:::shared
    end

    subgraph FA["features/auth"]
        AuthApi["api.ts (login · me)"]:::api
        AuthStore["store.useAuthStore<br/>persisted: token · user"]:::store
        AuthLogin["views/LoginView.vue"]:::view
        AuthLoginForm["components/LoginForm.vue"]:::view
        AuthGuard["composables/useAuthGuard"]:::shared
    end

    subgraph FC["features/cards"]
        CardsApi["api.ts<br/>listCards · getCard · publish · update · archive · remove"]:::api
        CardsStore["store.useCardsStore<br/>list · byId · filters · loading"]:::store
        CardsHome["views/HomeView.vue"]:::view
        CardsDetail["views/CardDetailView.vue"]:::view
        AdminCards["views/AdminCardsView.vue"]:::view
        AdminPub["views/AdminPublishView.vue"]:::view
        CardItem["components/CardItem · CardGrid · CardCover<br/>CardFilters · ArticleBody · ArticleHero · HeroBanner<br/>PublishForm · AdminCardTable"]:::view
        CardForm["composables/useCardForm · useFilters"]:::shared
    end

    subgraph FCo["features/covers"]
        CoversApi["api.ts (uploadCover)"]:::api
        Uploader["components/CoverUploader.vue"]:::view
        UseUpload["composables/useCoverUpload"]:::shared
    end

    subgraph FT["features/tags"]
        TagsApi["api.ts (listTags)"]:::api
        TagsStore["store.useTagsStore"]:::store
        TagCloud["components/TagCloud.vue"]:::view
    end

    subgraph SS["stores/"]
        UiStore["ui.useUiStore<br/>keyword · theme · toasts · modal · sidebarCollapsed<br/>persisted: theme · sidebarCollapsed"]:::store
    end

    Backend[("FastAPI<br/>/api/v1/*")]:::ext
    LS[("localStorage<br/>lg_auth · lg_ui")]:::ext

    Main --> AppRoot
    AppRoot --> Router
    AppRoot --> Public
    AppRoot --> Admin
    AppRoot --> Blank
    Public --> CardsHome
    Public --> CardsDetail
    Admin --> AdminCards
    Admin --> AdminPub
    Blank --> AuthLogin

    AuthLogin --> AuthLoginForm
    AuthLoginForm --> AuthStore
    AuthStore --> AuthApi
    AuthGuard --> AuthStore

    CardsHome --> CardsStore
    CardsDetail --> CardsStore
    AdminCards --> CardsStore
    AdminPub --> CardForm
    CardForm --> CardsStore
    CardsStore --> CardsApi
    CardItem --> CardsStore
    TagCloud --> CardsStore
    TagCloud --> TagsStore
    TagsStore --> TagsApi

    AdminPub --> Uploader
    Uploader --> UseUpload
    UseUpload --> CoversApi

    CardsApi --> ApiClient
    AuthApi --> ApiClient
    TagsApi --> ApiClient
    CoversApi --> ApiClient
    ApiClient --> ApiInterc
    ApiInterc --> ApiErr
    ApiClient --> Schema
    ApiInterc --> AuthStore
    ApiClient --> Backend

    AuthStore --> LS
    UiStore --> LS

    UI --- AppRoot
    Composables --- CardsDetail
    Composables --- AdminPub
```

## Layered rules

| Layer | Owns | Imports allowed | Forbidden |
|---|---|---|---|
| `views/` | Page composition, route data fetch | feature `api.ts`, feature stores, components, composables | global stores, direct `api` client |
| `components/` | Reusable visuals; emit events, accept props | shared/ui, shared/composables | feature stores (use props/emits instead) |
| `features/<x>/api.ts` | Typed thin wrappers around `openapi-fetch` | `shared/api/client` | other features' APIs |
| `features/<x>/store.ts` | Pinia setup store; mutations via actions | feature `api.ts`, `shared/api/errors` | DOM, router |
| `shared/api/*` | API client + interceptors + AppError | `openapi-fetch`, generated `schema.d.ts` | features |
| `shared/composables/*` | Reusable composables | Vue runtime, `@vueuse/core` | feature stores |
| `shared/ui/*` | Base primitives | Vue runtime | feature stores, API |
| `router/*` | Route table + guards | layouts, lazy view imports | feature stores at module scope (use guard fn) |

## API client middleware

```mermaid
sequenceDiagram
    autonumber
    participant V as view / store action
    participant W as features/<x>/api.ts
    participant C as shared/api/client.ts
    participant Mid as middleware (Bearer · onResponse)
    participant Win as window event bus
    participant Auth as useAuthStore
    participant R as router

    V->>W: listCards(filters)
    W->>C: api.GET('/cards', { params })
    C->>Mid: onRequest(req)
    Mid->>Auth: token = useAuthStore().token
    Mid-->>C: req.headers.Authorization = 'Bearer ...'
    C-->>W: 200 list[CardListItem]

    Note over V,W: Token expired path
    V->>W: getCard(slug)
    W->>C: api.GET('/cards/{slug}', ...)
    C-->>Mid: onResponse: 401
    Mid->>Mid: parse envelope → AppError(code='unauthenticated')
    Mid->>Win: dispatch 'auth:invalidated'
    W-->>V: throw AppError
    Win->>Auth: listener (App.vue, mounted once)
    Auth->>Auth: $reset()
    Auth->>R: if route.meta.requiresAdmin → push('/admin/login?next=...')
```

## Routes + guards

```mermaid
flowchart LR
    classDef pub fill:#1e293b,stroke:#38bdf8,color:#e0f2fe;
    classDef adm fill:#0f172a,stroke:#a78bfa,color:#ede9fe;
    classDef anon fill:#111827,stroke:#fbbf24,color:#fef3c7;
    classDef nf fill:#020617,stroke:#94a3b8,color:#cbd5e1;

    Home["/<br/>HomeView<br/>layout: public"]:::pub
    Detail["/card/:slug<br/>CardDetailView<br/>layout: public"]:::pub
    Login["/admin/login<br/>LoginView<br/>layout: blank · anonOnly"]:::anon
    AdminCards["/admin<br/>AdminCardsView<br/>layout: admin · requiresAdmin"]:::adm
    AdminPublish["/admin/publish<br/>AdminPublishView<br/>layout: admin · requiresAdmin"]:::adm
    AdminEdit["/admin/publish/:id<br/>AdminPublishView<br/>layout: admin · requiresAdmin"]:::adm
    NotFound["/:pathMatch(.*)*<br/>NotFoundView<br/>layout: blank"]:::nf

    Login -- "redirectIfAuthed" --> AdminCards
    AdminCards -- "requireAdmin miss" --> Login
    AdminPublish -- "requireAdmin miss" --> Login
    AdminEdit -- "requireAdmin miss" --> Login
```
