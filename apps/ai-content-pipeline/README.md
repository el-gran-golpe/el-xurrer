# AI Content Pipeline

Typer CLI app for AI creator content workflows: planning, generation, scheduling, Instagram publishing, Fanvue publishing orchestration, Google Drive sync, ComfyUI, and LLM routing.

## Run

Run commands from the repository root:

```bash
uv run python apps/ai-content-pipeline/main.py --help
uv run python apps/ai-content-pipeline/main.py meta plan -p 0
uv run python apps/ai-content-pipeline/main.py meta generate -p 0
uv run python apps/ai-content-pipeline/main.py meta schedule -p 0
uv run python apps/ai-content-pipeline/main.py all run_all -p 0
```

## Meta / Instagram Auth

Instagram publishing uses the Instagram API with Facebook Login through
`graph.facebook.com`. Each profile needs credentials for the Facebook Page linked to
that profile's Instagram professional account:

```dotenv
LAURA_VIGNE_INSTAGRAM_ACCOUNT_ID=178...
LAURA_VIGNE_FACEBOOK_PAGE_ID=123...
LAURA_VIGNE_FACEBOOK_PAGE_ACCESS_TOKEN=EA...
```

Keep these separate from the shared CDN staging credentials:

```dotenv
FACEBOOK_STAGING_PAGE_ID=123...
FACEBOOK_STAGING_PAGE_ACCESS_TOKEN=EA...
```

`all run_all` validates selected profiles' Page tokens before clearing outputs or
starting planning/generation. The Meta publishing path also validates before upload.

To obtain profile Page tokens, use Meta's Graph API Explorer or the official
Instagram Postman collection with a Business app. Generate a Facebook User Access
Token with `pages_show_list`, `pages_read_engagement`, `instagram_basic`, and
`instagram_content_publish`; exchange it for a long-lived user token; call
`GET https://graph.facebook.com/v21.0/me/accounts?fields=name,id,access_token,instagram_business_account`;
then save the Page row whose `instagram_business_account.id` matches the profile's
Instagram account. Do not log or paste tokens; rotate any token that has been
shared in chat.

## Tests

```bash
uv run pytest apps/ai-content-pipeline/tests -q
```

## Notes

- Runtime profile data lives in the repository root `resources/` folder.
- Commands that sync resources, generate media, authenticate, upload, schedule, or publish have external side effects.
- Instagram assets must remain safe for work. Fanvue-specific content belongs only in Fanvue resources and outputs.
