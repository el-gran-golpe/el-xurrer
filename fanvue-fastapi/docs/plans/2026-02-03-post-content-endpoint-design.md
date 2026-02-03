# Post Content Endpoint Design

## Overview

Add an endpoint to create posts on Fanvue with text and/or media attachments, supporting scheduled publishing.

## API Endpoint

**Endpoint:** `POST /api/posts`

**Request:** Multipart form data

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | No* | Post content |
| `files` | file[] | No* | Images/videos to attach |
| `audience` | string | No | `"subscribers"` (default) or `"followers-and-subscribers"` |
| `publishAt` | string | No | UTC ISO 8601 timestamp. Omit for immediate publishing |

*At least one of `text` or `files` must be provided.

**Response (201 Created):**

```json
{
  "uuid": "post-uuid",
  "createdAt": "2024-03-15T10:00:00Z",
  "text": "Hello world",
  "audience": "subscribers",
  "publishAt": "2024-03-15T12:00:00Z",
  "mediaUuids": ["uuid-1", "uuid-2"],
  "uploadFailures": [
    {"filename": "video.mp4", "error": "Upload timeout"}
  ]
}
```

The `uploadFailures` array is empty if all uploads succeeded, otherwise contains details of failed uploads.

**Errors:**

| Status | Description |
|--------|-------------|
| 400 | Validation error (no content provided, invalid audience, all uploads failed) |
| 401 | Not authenticated |
| 502 | Fanvue API error |

## Internal Flow

1. **Authentication**
   - Extract session from cookie (reuse `require_session` dependency)
   - Auto-refresh token if expiring (reuse logic from `get_current_user`)

2. **Validation**
   - Check at least one of `text` or `files` is provided
   - Validate `audience` is one of the allowed enum values

3. **Media Upload** (if files present)

   For each file, sequentially:
   - `POST /media/uploads` → get `mediaUuid` and `uploadId`
   - Chunk file into ~10MB parts
   - For each chunk: get signed URL, PUT to cloud storage, collect ETag
   - `PATCH /media/uploads/{uploadId}` with ETags to complete
   - On failure: log warning, add to `uploadFailures`, continue to next file

4. **Create Post**
   - `POST /posts` with collected `mediaUuids`, `text`, `audience`, `publishAt`
   - If no `mediaUuids` and no `text` (all uploads failed with no text), return 400

5. **Response**
   - Return Fanvue's post response merged with `uploadFailures` array

## Code Structure

### New Files

**`app/routes/posts.py`**
- `POST /api/posts` endpoint
- Request validation with Pydantic model
- Orchestrates upload + post creation flow

**`app/media.py`**
- `upload_media(file, access_token) -> MediaUploadResult`
- Handles 3-phase multipart upload for a single file
- Chunking logic (10MB chunks)
- Returns `mediaUuid` on success or error details on failure

**`app/posts.py`**
- `create_post(text, media_uuids, audience, publish_at, access_token) -> dict`
- Calls Fanvue's `POST /posts` endpoint

**`app/schemas/posts.py`**
- `CreatePostRequest` - Pydantic model for form data validation
- `CreatePostResponse` - Response model
- `UploadFailure` - Model for failed upload details

### Modified Files

**`app/fanvue.py`**
- Extract token refresh into `ensure_valid_token(session) -> (access_token, updated_session)`
- `get_current_user` will use this helper internally

**`main.py`**
- Register the posts router: `app.include_router(posts_router)`

## Fanvue API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/media/uploads` | POST | Create upload session, get `mediaUuid` and `uploadId` |
| `/media/uploads/{uploadId}/parts/{partNumber}/url` | GET | Get signed URL for chunk upload |
| `/media/uploads/{uploadId}` | PATCH | Complete upload with ETags |
| `/posts` | POST | Create the post |

All endpoints require `Authorization: Bearer <token>` header.

## Configuration

### Required OAuth Scopes

Add to `OAUTH_SCOPES` in `.env`:
- `write:post` - Create posts
- `write:media` - Upload media

These must also be enabled in the Fanvue Developer Area UI.

### Constants

```python
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Upload approach | Server-proxied | Simpler client code, can add direct uploads later |
| API design | Single endpoint | Simpler integration, atomic operation |
| Multiple files | Supported | User requirement |
| Audience default | `"subscribers"` | Most content goes to paying subscribers |
| Timezone | UTC only | Simpler, client converts before sending |
| Missing/past `publishAt` | Publish immediately | Expected behavior |
| Upload failures | Best effort + logging | Continue with remaining files, warn on failures |
| File validation | Fanvue's limits (1GB) | Keep simple, let API validate |
| Price field | Skipped | YAGNI |
| Expiration field | Skipped | YAGNI |

## Not Included

- Retry logic for failed chunks (can add if uploads prove flaky)
- Progress callbacks / real-time tracking
- Draft posts (not in Fanvue API)
- Deleting/editing posts (separate feature)
- Client-direct uploads (can add later for large files)
