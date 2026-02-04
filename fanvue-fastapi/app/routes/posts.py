from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)

from app.dependencies import require_session
from app.fanvue import ensure_valid_token
from app.media import upload_media
from app.posts import create_post, PostCreationError
from app.schemas.posts import Audience, CreatePostResponse, UploadFailure
from app.session import SessionPayload, create_session_token

router = APIRouter(prefix="/api/posts", tags=["posts"])

SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@router.post("", response_model=CreatePostResponse, status_code=201)
async def create_post_endpoint(
    request: Request,
    text: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(default=[]),
    audience: Audience = Form(default=Audience.SUBSCRIBERS),
    publishAt: Optional[str] = Form(default=None),
    session: SessionPayload = Depends(require_session),
) -> Response:
    """Create a post on Fanvue with optional media attachments."""
    from app.config import get_settings

    settings = get_settings()

    # Validate at least text or files provided
    if not text and not files:
        raise HTTPException(
            status_code=400, detail="At least text or files must be provided"
        )

    # Get valid token (refresh if needed)
    access_token, updated_session = await ensure_valid_token(session)

    # Upload files sequentially
    media_uuids: List[str] = []
    upload_failures: List[UploadFailure] = []

    for file in files:
        result = await upload_media(file, access_token)
        if result.success and result.media_uuid:
            media_uuids.append(result.media_uuid)
        else:
            upload_failures.append(
                UploadFailure(
                    filename=result.filename or "unknown",
                    error=result.error or "Unknown error",
                )
            )

    # If all uploads failed and no text, return error
    if not media_uuids and not text:
        raise HTTPException(
            status_code=400,
            detail="All file uploads failed and no text provided",
        )

    # Create the post
    try:
        post_data = await create_post(
            text=text,
            media_uuids=media_uuids,
            audience=audience.value,
            publish_at=publishAt,
            access_token=access_token,
        )
    except PostCreationError as e:
        raise HTTPException(status_code=502, detail=f"Fanvue API error: {e.message}")

    # Build response
    response_data = CreatePostResponse(
        uuid=post_data.get("uuid", ""),
        createdAt=post_data.get("createdAt", ""),
        text=post_data.get("text"),
        audience=post_data.get("audience", audience.value),
        publishAt=post_data.get("publishAt"),
        mediaUuids=media_uuids,
        uploadFailures=upload_failures,
    )

    # Create response object
    from fastapi.responses import JSONResponse

    response = JSONResponse(content=response_data.model_dump(), status_code=201)

    # Update session cookie if token was refreshed
    if updated_session:
        session_token = create_session_token(updated_session)
        secure = request.url.scheme == "https"
        response.set_cookie(
            key=settings.session_cookie_name,
            value=session_token,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=SESSION_COOKIE_MAX_AGE,
            path="/",
        )

    return response
