import os
import uvicorn
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse

# Removed unused import
from app.routes.oauth import router as oauth_router
from app.routes.posts import router as posts_router
from app.dependencies import get_session_from_cookie, require_session
from app.fanvue import get_current_user
from app.session import SessionPayload

app = FastAPI(title="Fanvue OAuth App")

app.include_router(oauth_router)
app.include_router(posts_router)

if __name__ == "__main__":
    # Default configuration with environment variable overrides
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() in ("true", "1", "yes")

    # Startup message
    print(f"Starting Fanvue OAuth App on {host}:{port} (Reload: {reload})")

    # Run the server
    uvicorn.run("main:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    # Default configuration with environment variable overrides
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() in ("true", "1", "yes")

    # Startup message
    print(f"Starting Fanvue OAuth App on {host}:{port} (Reload: {reload})")

    # Run the server
    uvicorn.run("main:app", host=host, port=port, reload=reload)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page showing login status."""
    session = get_session_from_cookie(request)

    if session:
        user, _ = await get_current_user(session)

        # If session was updated (token refreshed), we'd need to set new cookie
        # For simplicity, just show user info
        if user:
            username = user.get("displayName", "User")
            user_id = user.get("uuid", "N/A")
            return f"""
            <html>
                <body>
                    <h1>Welcome, {username}!</h1>
                    <p>User ID: {user_id}</p>
                    <form action="/api/oauth/logout" method="post">
                        <button type="submit">Logout</button>
                    </form>
                </body>
            </html>
            """

    return """
    <html>
        <body>
            <h1>Fanvue OAuth Demo</h1>
            <a href="/api/oauth/login">Login with Fanvue</a>
        </body>
    </html>
    """


@app.get("/api/user")
async def get_user(session: SessionPayload = Depends(require_session)):
    """Get current user (protected endpoint)."""
    user, _ = await get_current_user(session)
    if not user:
        return {"error": "Failed to fetch user"}
    return user
