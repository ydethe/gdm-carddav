# Specifications: gdm_carddav

A read-only CardDAV server that exposes contacts from an existing PostgreSQL genealogy database to standard CardDAV clients.

## 1. Goals

- Serve contacts from the `public.People` PostgreSQL table as vCard 3.0 resources over the CardDAV protocol (RFC 6352).
- Support all major CardDAV clients: Apple Contacts (macOS/iOS), Thunderbird, GNOME Contacts, DAVx5, Evolution.
- Treat the database as **read-only**: never issue INSERT, UPDATE, or DELETE statements.
- Silently accept write requests from clients (PUT, DELETE on contacts) without persisting changes, and log each attempt with loguru.

## 2. Protocol Scope

### 2.1 Supported RFCs

| RFC | Description | Support level |
|-----|-------------|---------------|
| RFC 4918 | WebDAV | Subset required by CardDAV |
| RFC 6352 | CardDAV | Full read path, write methods accepted but no-op |
| RFC 6578 | WebDAV Sync (sync-token) | Required for efficient client sync |
| RFC 2425 / RFC 6350 | vCard 3.0 / 4.0 | vCard 3.0 output (widest client compatibility) |

### 2.2 HTTP Methods

| Method | Path pattern | Behavior |
|--------|-------------|----------|
| `OPTIONS` | `*` | Advertise DAV capabilities |
| `PROPFIND` | `/`, `/{principal}/`, `/{principal}/contacts/` | Discovery and collection properties |
| `REPORT` | `/{principal}/contacts/` | `addressbook-query`, `addressbook-multiget`, `sync-collection` |
| `GET` | `/{principal}/contacts/{uid}.vcf` | Return a single vCard |
| `HEAD` | `/{principal}/contacts/{uid}.vcf` | Return headers only |
| `PUT` | `/{principal}/contacts/{uid}.vcf` | Accept silently, log, return `201 Created` (no-op) |
| `DELETE` | `/{principal}/contacts/{uid}.vcf` | Accept silently, log, return `204 No Content` (no-op) |

### 2.3 Well-Known URI

The server must handle `/.well-known/carddav` and redirect (HTTP 301) to the principal URL so that clients can auto-discover the address book.

## 3. URL Layout

```
/                                        # DAV root
/.well-known/carddav                     # Auto-discovery redirect
/principals/{username}/                   # Principal resource
/principals/{username}/contacts/          # Address book collection
/principals/{username}/contacts/{uid}.vcf # Individual contact
```

Since the database is shared and read-only, all authenticated users see the same address book. The `{username}` segment exists solely for protocol compliance; the underlying data does not vary per user.

## 4. Authentication

- **Method**: HTTP Basic Authentication over TLS.
- Credentials are checked against a static configuration (environment variables or a config file), not against the PostgreSQL database.
- Configuration model (via `pydantic-settings`):

| Variable | Description |
|----------|-------------|
| `CARDDAV_USERNAME` | Allowed username |
| `CARDDAV_PASSWORD` | Allowed password (hashed with bcrypt) |

- Multiple users may be supported in the future via a `users.yaml` file; V1 targets a single shared credential.
- Unauthenticated requests receive `401 Unauthorized` with a `WWW-Authenticate: Basic realm="gdm_carddav"` header.

## 5. Data Source: PostgreSQL Schema

The server connects to a PostgreSQL 16 database in **read-only** mode (the connection string should use a read-only database user). The source table is `public."People"`.

### 5.1 Column Inventory

| Column | Type | Nullable | vCard mapping |
|--------|------|----------|---------------|
| `id` | integer (PK) | NO | Used to derive the stable vCard UID |
| `prenom` | varchar(255) | NO | `N` given name / `FN` |
| `nom` | varchar(255) | NO | `N` family name / `FN` |
| `sexe` | enum `enum_People_sexe` | NO | `X-GENDER` |
| `email` | varchar(255) | YES | `EMAIL;TYPE=HOME` |
| `tel` | varchar(255) | YES | `TEL;TYPE=CELL` |
| `photo` | varchar(255) | YES | `PHOTO;VALUE=URI` |
| `adresse` | varchar(255) | YES | `ADR` street (home) |
| `ville` | varchar(255) | YES | `ADR` locality (home) |
| `codePostal` | varchar(255) | YES | `ADR` postal code (home) |
| `adresse2` | varchar(255) | YES | `ADR` street (work/secondary) |
| `ville2` | varchar(255) | YES | `ADR` locality (work/secondary) |
| `codePostal2` | varchar(255) | YES | `ADR` postal code (work/secondary) |
| `latitude` | double | YES | `GEO` (home) |
| `longitude` | double | YES | `GEO` (home) |
| `latitude2` | double | YES | _Not mapped in V1_ |
| `longitude2` | double | YES | _Not mapped in V1_ |
| `dateNaissance` | varchar(255) | YES | `BDAY` |
| `lieuNaissance` | varchar(255) | YES | `BIRTHPLACE` (RFC 6474) |
| `estDecede` | boolean | YES | `X-DECEASED` (custom extension) |
| `dateDeces` | varchar(255) | YES | `DEATHDATE` (RFC 6474) |
| `estMarie` | boolean | YES | _Not mapped_ |
| `dateMariage` | varchar(255) | YES | `ANNIVERSARY` |
| `metier` | varchar(255) | YES | `TITLE` |
| `notes` | varchar(250) | YES | `NOTE` |
| `updatedAt` | timestamptz | NO | `REV` (last-modified timestamp) |
| `createdAt` | timestamptz | NO | _Used for ETag / sync_ |

Columns not listed above (`idPere`, `idMere`, `idGeneration`, `estNeFamille`, `branche`, `brancheLabel`, `requestType`, `status`, `hasACurrentRequest`, `modifiedPersonId`, `allPersonId`, `familyStatus`, `createdByUserId`) are genealogy-management metadata and are **not exposed** through the CardDAV interface.

### 5.2 Contact Filtering

Only rows meeting **all** of the following conditions are exposed as contacts:

- `estDecede IS FALSE OR estDecede IS NULL` (exclude deceased persons)
- `status = 'approved'` (only validated records)
- `email IS NOT NULL AND email!=''` (only people with email)

This filter is applied at the repository layer and is not configurable by clients.

### 5.3 UID Generation

Each contact's CardDAV UID is derived deterministically from the database primary key:

```
UID: gdm-{id}@gdm_carddav
```

This guarantees stability across server restarts and allows clients to track contacts over time.

## 6. vCard Generation

### 6.1 Format

vCard 3.0 (RFC 2426) for maximum client compatibility. The `VERSION:3.0` property is always present.

### 6.2 Example Output

```vcf
BEGIN:VCARD
VERSION:3.0
UID:gdm-42@gdm_carddav
FN:Jean Dupont
N:Dupont;Jean;;;
EMAIL;TYPE=HOME:jean.dupont@example.com
TEL;TYPE=CELL:+33612345678
ADR;TYPE=HOME:;;12 rue de la Paix;Paris;;75002;France
GEO:48.8698;2.3311
BDAY:1985-03-15
ANNIVERSARY:2010-06-20
TITLE:Ingenieur
NOTE:Some notes about this contact
PHOTO;VALUE=URI:https://example.com/photos/jean.jpg
REV:2025-01-15T10:30:00Z
END:VCARD
```

### 6.3 Field Rules

- `FN` is built as `"{prenom} {nom}"`.
- `N` is built as `"{nom};{prenom};;;"`.
- Empty/null database fields are **omitted** from the vCard (not emitted as empty properties).
- `dateNaissance`, `dateDeces`, `dateMariage` are stored as varchar in the database. The server must parse them and emit ISO 8601 date format (`YYYY-MM-DD`). If parsing fails, the field is omitted and a warning is logged.
- `PHOTO` is emitted as a URI reference (`PHOTO;VALUE=URI:{url}`), not as inline base64.

## 7. Sync Mechanism

### 7.1 ETag

Each contact resource has an ETag derived from:

```
ETag: "{id}-{updatedAt_unix_timestamp}"
```

This allows clients to detect changes without downloading full vCards.

### 7.2 CTag (Collection Tag)

The address book collection exposes a `getctag` property (used by Apple clients) computed as:

```
CTag: max(updatedAt) across all exposed contacts, as a Unix timestamp string
```

### 7.3 sync-token (RFC 6578)

The `sync-collection` REPORT is supported. The sync token encodes the high-water mark of `updatedAt`:

```
sync-token: https://gdm_carddav/sync/{unix_timestamp_microseconds}
```

When a client presents a previous sync-token, the server returns only contacts with `updatedAt` strictly greater than the encoded timestamp.

Since the database is read-only from this server's perspective, deletions are not tracked. If a record disappears from the filtered result set (e.g., `status` changes away from `approved`), the server reports it as a `404` response element in the sync diff.

## 8. Architecture

Following the project's layered architecture (Router -> Service -> Repository):

```
┌──────────────────────────────────────────┐
│              CardDAV Router              │
│  (HTTP/WebDAV methods, XML parsing)      │
├──────────────────────────────────────────┤
│              CardDAV Service             │
│  (vCard generation, sync logic, ETags)   │
├──────────────────────────────────────────┤
│            People Repository             │
│  (SQLAlchemy read-only queries)          │
├──────────────────────────────────────────┤
│          PostgreSQL (read-only)          │
└──────────────────────────────────────────┘
```

### 8.1 Router Layer

- Handles WebDAV/CardDAV HTTP methods.
- Parses and generates XML request/response bodies (using `lxml` or `xml.etree`).
- Performs authentication.
- No direct database access.

### 8.2 Service Layer

- Converts `People` domain objects to vCard strings.
- Computes ETags, CTag, and sync-tokens.
- Implements the filtering logic (deceased, status).
- No HTTP/XML types.

### 8.3 Repository Layer

- SQLAlchemy 2.x async ORM model for the `People` table.
- Read-only queries: `SELECT` only, no write operations.
- Uses SQLAlchemy's `reflect` or explicit model mapping against the existing table.

## 9. Configuration

All settings via environment variables (loaded by `pydantic-settings`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | - | PostgreSQL connection string (read-only user) |
| `CARDDAV_USERNAME` | Yes | - | Basic auth username |
| `CARDDAV_PASSWORD` | Yes | - | Basic auth password (bcrypt hash) |
| `CARDDAV_REALM` | No | `gdm_carddav` | HTTP Basic auth realm |
| `CARDDAV_HOST` | No | `0.0.0.0` | Bind address |
| `CARDDAV_PORT` | No | `8080` | Bind port |
| `LOGLEVEL` | No | `info` | Logging level |

## 10. Write Request Handling

Since the database is read-only, write operations are handled as follows:

| Operation | HTTP Response | Side Effect |
|-----------|--------------|-------------|
| `PUT` (create/update contact) | `201 Created` | Log with loguru at `WARNING` level |
| `DELETE` (remove contact) | `204 No Content` | Log with loguru at `WARNING` level |
| `MKCOL` | `201 Created` | Log with loguru at `WARNING` level |
| `PROPPATCH` | `207 Multi-Status` (success) | Log with loguru at `WARNING` level |

Logged information includes: timestamp, authenticated user, method, target URI, and request body size.

## 11. Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP framework |
| `uvicorn` | ASGI server |
| `sqlalchemy[asyncio]` | Async ORM for PostgreSQL |
| `asyncpg` | Async PostgreSQL driver |
| `pydantic` / `pydantic-settings` | Configuration and validation |
| `loguru` | Logging |
| `lxml` | XML parsing for WebDAV requests/responses |
| `bcrypt` | Password hashing for Basic Auth |
| `vobject` | vCard generation |

## 12. Testing Strategy

- **Unit tests**: vCard generation from `People` model objects, ETag/CTag computation, date parsing.
- **Integration tests**: Full PROPFIND/REPORT/GET request cycles against an SQLite in-memory database.
- **Client compatibility tests**: Manual verification with Apple Contacts, Thunderbird, and DAVx5.
- All tests use `pytest` + `pytest-asyncio` with the `@pytest.mark.asyncio` decorator.

## 13. Non-Goals (V1)

- Multi-address-book support (one shared address book per deployment).
- Per-user access control or row-level security.
- Write-back to PostgreSQL.
- vCard 4.0 (may be added later if client demand exists).
- Full-text search (CardDAV `addressbook-query` with text filters is supported via SQL `ILIKE`).
- Photo proxying or thumbnail generation.
