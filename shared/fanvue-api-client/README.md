# Fanvue API Client

Shared Fanvue helpers used by both apps.

## Contents

- `oauth.py` - OAuth token exchange and refresh helpers.
- `media.py` - media upload helpers.
- `posts.py` - post creation helper.
- `token_store.py` - local token file storage.

## Tests

Run from the repository root:

```bash
uv run pytest shared/fanvue-api-client/tests -q
```
