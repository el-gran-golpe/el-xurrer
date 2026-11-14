# Meta Instagram Page Token Runbook

This runbook documents the reusable flow for creating a profile-specific Meta
setup and obtaining the non-expiring Facebook Page access token used by this repo
to publish Instagram content.

It covers account email and recovery setup, Facebook Page and Instagram linking,
Meta Business Suite, Meta for Developers, Graph API Explorer permissions, Graph
API version notes, and the local token exchange helper.

## Goal

For each influencer profile, produce these repository `.env` values:

```dotenv
EXAMPLE_CREATOR_FACEBOOK_PAGE_ID=<facebook-page-id>
EXAMPLE_CREATOR_INSTAGRAM_ACCOUNT_ID=<instagram-account-id>
EXAMPLE_CREATOR_FACEBOOK_PAGE_ACCESS_TOKEN=<facebook-page-access-token>
```

The Page token should report `expires_at: 0` from Meta `debug_token`. Meta calls
this non-expiring, but it can still be revoked if Page permissions, app status,
business ownership, the Facebook user session, or the Page to Instagram link
changes.

## Example Values

```text
Profile alias: example_creator
Environment prefix: EXAMPLE_CREATOR
Facebook Page name: Example Creator
Facebook Page ID: <facebook-page-id>
Meta app ID: <meta-app-id>
Controlling email: <mailbox-you-directly-control>
```

Do not commit, paste, or document the Meta app secret, short-lived user token,
long-lived user token, Page access token, `.env`, token files, or screenshots that
show token values.

If any token or app secret has been pasted into chat, browser screenshots, issue
trackers, or docs, rotate it before relying on the setup.

## Critical Concepts

The most confusing part is that Meta uses several different objects with similar
names. Keep them separate.

| Object | What It Is | Used For |
| --- | --- | --- |
| Facebook personal account | A real user login | Owns/administers Pages, creates apps, authorizes Graph API Explorer |
| Facebook Page | The public Page asset, such as Example Creator | Must be linked to the Instagram professional account |
| Instagram professional account | Business or Creator Instagram account | The actual IG account that receives published content |
| Meta Business Suite portfolio | Business asset container | Manages Page and Instagram assets and permissions |
| Meta Developer app | OAuth/API client | Used to generate/exchange tokens, not the publishing identity itself |
| User access token | Token for the Facebook personal account | Short-lived token from Graph API Explorer, then exchanged for long-lived token |
| Page access token | Token for the Facebook Page | Final token stored in `.env` and used by this repo for publishing |

Important consequences:

- You do not add a Meta app to another Meta app.
- App roles accept Facebook personal accounts, not Pages, Instagram accounts, or app IDs.
- The Python publisher does not require one profile's Facebook account to be added to another profile's app when each profile has its own app and Page token.
- Page tokens generated through different Meta apps can coexist in the same runtime configuration.
- The repo publishes through `graph.facebook.com` using Facebook Page tokens, not `graph.instagram.com` Instagram user tokens.

## Graph API Version Notes

The current Meta publisher and standalone token helper both target Graph API
`v25.0` through `https://graph.facebook.com/v25.0`.

The Page token itself is not a separate `v25 token`; the requests used to obtain
or use it are versioned. Existing valid tokens do not need to be regenerated
solely because the request URL moves to a newer Graph API version.

Operational guidance:

- In Graph API Explorer, select `v25.0` for this setup.
- Keep the helper's inline `GRAPH_API_BASE_URL` aligned with the publisher's Graph API version.
- Review Meta's changelog and test the full Page-validation, media-staging, and Instagram-publishing flow before a future version upgrade.

## Step 1: Account Email And Recovery Hardening

This step is the single most important one in the runbook. Everything else can be
redone; a lost account email cannot.

Use a mailbox you control directly, such as a dedicated Gmail account for the
project. Do not put the profile's Facebook login behind a mail-forwarding hop you
do not own outright.

```text
Controlling email: <mailbox-you-directly-control>
```

Before creating any Meta asset, harden the Facebook personal account that will
control the Page:

```text
Login email:      a mailbox you can still open in a year
Phone number:     added and verified
Two-factor:       authenticator app, not SMS-only
Recovery codes:   saved in the password manager
Page admins:      a second Facebook account you control, with full control
```

Why this step exists: a profile was permanently lost when the domain behind its
forwarded account email lapsed. The Meta assets still existed, but every account
recovery email went to a mailbox that no longer resolved, so the Facebook Page and
Instagram account could not be recovered at any price. Expired domains are
recoverable only during a roughly 30-day redemption window, at a restore fee, and
only through the original registrar.

Optional, and not required by any later step: a public website or subdomain for
the influencer. If you use a custom domain for persona credibility, keep it on
auto-renew with a payment method that will not lapse, register it under the
controlling email, and still set the account email and recovery options above
directly on the Meta accounts. A domain must never be the only path to account
recovery.

Note that `FACEBOOK_STAGING_PAGE_ID` and `FACEBOOK_STAGING_PAGE_ACCESS_TOKEN` are
shared by every profile. Losing access to the account that controls the staging
Page breaks Instagram publishing for all profiles at once, so harden that account
with the same checklist.

## Step 2: Create The Facebook Page

Create the Facebook Page for the influencer.

Example values:

```text
Facebook Page name: Example Creator
Facebook Page ID: <facebook-page-id>
```

Confirm in Meta Business Suite or Business Settings:

```text
Page: Example Creator
Full control: assigned to the controlling Facebook personal account
Owned by: the intended business portfolio or business owner
```

Why this matters:

- The final token is a Facebook Page access token.
- Instagram publishing with Facebook Login requires a Facebook Page linked to the IG professional account.
- If `/me/accounts` does not list the Page, try direct Page lookup before assuming the user token cannot produce the Page token.

Common mistakes:

- The Page ID is not the Facebook personal user ID.
- The Page cannot be added as an app role in Meta Developers.
- The Page is not the same thing as the Business Suite portfolio.

## Step 3: Create And Prepare The Instagram Account

Create the Instagram account either directly in Meta Business Suite or through
Instagram. If it is created through Instagram, convert it to a professional
account before continuing.

Either professional type can work for this setup:

```text
Creator account
Business account
```

The important requirement is that the Instagram account is professional and can be
linked to a Facebook Page.

Confirm in Instagram or Meta Business Suite:

```text
Instagram account: Example Creator
Professional mode: Creator or Business
Linked Facebook Page: Example Creator
```

Common mistakes:

- A personal Instagram account is not enough.
- Linking the wrong Page will make validation fail later.
- The visible Instagram username is not the same as the numeric Instagram business account ID used by the API.

## Step 4: Link Instagram To The Facebook Page In Meta Business Suite

Open Meta Business Suite or Business Settings and connect the Instagram account to
the Facebook Page.

Expected result:

```text
Facebook Page: Example Creator
Connected asset: Example Creator Instagram professional account
People: controlling Facebook user has full control
```

This link is what makes this Graph API call return an Instagram business account:

```text
GET /<facebook-page-id>?fields=instagram_business_account
```

Common mistakes:

- Being logged into the wrong Facebook personal account.
- Creating a Page but not assigning full control to the user that will generate the token.
- Connecting the Instagram account to a different Page than the one used in `.env`.
- Assuming Business Suite linking is optional. It is required for this Page-token publishing flow.

## Step 5: Create Or Choose The Meta Developer App

Use Meta for Developers:

```text
https://developers.facebook.com/apps/
```

For an isolated setup, create a profile-specific Meta Developer app.

Why a profile-specific app can be simpler:

- The controlling Facebook user can create and use the profile-specific app directly.
- There is no need to add that user as a role on another profile's app.
- App-level rate limits and app-level risk are isolated from other profile-specific apps.

For a central setup, one app can technically generate tokens for multiple Pages,
but the same Facebook personal account must both see the app and control the Pages.
Mixing app visibility with Page control is a common source of setup confusion.

## Step 6: Understand App Roles Before Trying To Add People

If Graph API Explorer says this while logged in as the controlling Facebook user:

```text
Create an app to get started
It looks like you currently don't have any apps available.
```

That means the current Facebook personal account cannot see any Meta Developer
apps. It does not mean the Facebook Page is missing.

If trying to add the controlling user to a central/shared app, Meta app roles
require a Facebook personal account that is registered as a Facebook Developer
account.

This will not work:

```text
Facebook Page ID
Instagram account
Business Suite portfolio
Meta app ID
```

This can work:

```text
Facebook personal login email
Facebook personal profile username
Facebook personal user ID
```

The confusing Meta message was:

```text
A Facebook Developer Account is required to be added to an app.
```

If you hit this, the Facebook personal account must first complete Meta Developer
registration at `https://developers.facebook.com/`.

Practical recommendation for this repo:

- Use a profile-specific app if app-role lookup or developer registration is blocking progress.
- Use one central app only if one central Facebook personal account can control all Pages and see the app.

## Step 7: Add The Correct Products And Permission Surface

In the profile's Meta Developer app, make sure the app is configured for the
Facebook Login based Instagram API flow.

Look for product/use-case names like:

```text
Instagram API with Facebook Login
Instagram Graph API
Facebook Login for Business
Facebook Login
```

Avoid using the Instagram Login-only flow for this repo.

If Graph API Explorer shows permissions like these instead:

```text
instagram_business_basic
instagram_business_content_publish
```

then you are likely in the newer Instagram Login permission set. That is not the
flow this repo currently uses.

For this repo, Graph API Explorer must be able to request:

```text
pages_show_list
pages_read_engagement
instagram_basic
instagram_content_publish
```

If `instagram_basic` and `instagram_content_publish` do not appear, the app is
usually missing the Instagram API with Facebook Login / Instagram Graph API setup.

## Step 8: Generate The Short-Lived User Token In Graph API Explorer

Open Graph API Explorer:

```text
https://developers.facebook.com/tools/explorer/
```

Select:

```text
Meta App: Example Creator app
User or Page: User Token
Graph API version: v25.0
```

Add permissions:

```text
pages_show_list
pages_read_engagement
instagram_basic
instagram_content_publish
```

Click:

```text
Get Token -> Get User Access Token
```

Approve the popup with the Facebook personal account that controls the Example
Creator Page. If Meta asks which assets to grant, select the Example Creator Page
and connected Instagram account.

The resulting token is a short-lived Facebook User access token. It is not the
final Page token.

Common mistakes:

- Reusing an app that was already authorized for an earlier profile. The previous Page-asset grant is remembered and the new Page is not added to it, so `/me/accounts` silently returns only the old Page. Add the new Page under `facebook.com/settings` -> Business Integrations before generating the token; see the troubleshooting section on the missing Page access token.
- Choosing `Get Page Access Token` first. Use `Get User Access Token`; the helper fetches the Page token safely from `/me/accounts`.
- Logging into Graph API Explorer with a Facebook user that can see the app but does not control the configured Page.
- Logging in with a Facebook user that controls the Page but cannot see the app.
- Pasting the short-lived token into chat. If this happens, generate a fresh token.

## Step 9: Sanity Check The Token In Graph API Explorer

Before running the helper, this Graph API Explorer request should work:

```text
me/accounts?fields=name,id,instagram_business_account
```

Expected shape:

```json
{
  "data": [
    {
      "name": "Example Creator",
      "id": "<facebook-page-id>",
      "instagram_business_account": {
        "id": "<instagram-account-id>"
      }
    }
  ]
}
```

If Example Creator is missing, also try this Graph API Explorer request:

```text
<facebook-page-id>?fields=id,name,access_token,instagram_business_account
```

If the direct Page request returns the Page `access_token` and Instagram business
account, the helper can still complete by using its direct Page lookup fallback.
If both `/me/accounts` and direct Page lookup fail, the token-generating Facebook
user likely does not have Page access, did not grant the Page asset in the auth
popup, or generated the token with the wrong app/account pairing.

If `instagram_business_account` is missing, the Instagram account is not linked to
that Facebook Page, is not professional, or the token lacks the right permissions.

## Step 10: Run The Local Exchange Helper

Open `apps/ai-content-pipeline/scripts/exchange_meta_page_token.py` and fill in
the constants inside the `if __name__ == "__main__"` block:

```python
GRAPH_API_BASE_URL = "https://graph.facebook.com/v25.0"
DEFAULT_PROFILE_ALIAS = "example_creator"
DEFAULT_PAGE_ID = "<facebook-page-id>"
META_APP_ID = "<meta-app-id>"
```

Then run the file from a PyCharm run configuration, or from the repository root:

```bash
uv run python apps/ai-content-pipeline/scripts/exchange_meta_page_token.py
```

The helper prompts for these using hidden input:

```text
Meta App Secret
Short-lived Graph API Explorer user token
```

The helper does this:

1. Calls `/oauth/access_token` to exchange the short-lived user token for a long-lived user token.
2. Calls `/me/accounts?fields=name,id,access_token,instagram_business_account` with the long-lived user token.
3. Finds the Page whose `id` is `<facebook-page-id>`.
4. If `/me/accounts` does not return the configured Page, calls `/{page_id}?fields=name,id,access_token,instagram_business_account` with the long-lived user token.
5. Extracts the Page access token from the Page payload.
6. Validates the Page token by calling `/{page_id}?fields=instagram_business_account`.
7. Calls `/debug_token` and requires `is_valid` to be `true`.
8. Writes the profile keys to the repository root `.env`, independent of the PyCharm working directory.
9. Creates a `.env*.bak.*` backup if `.env` already exists.
10. Prints a success summary to the console.

The helper never logs the Page token. It writes the token to the repository root
`.env` and reports only non-secret metadata in the console summary.

## Step 11: Confirm The `.env` Keys

The helper writes:

```dotenv
EXAMPLE_CREATOR_FACEBOOK_PAGE_ID=<facebook-page-id>
EXAMPLE_CREATOR_INSTAGRAM_ACCOUNT_ID=<instagram-account-id>
EXAMPLE_CREATOR_FACEBOOK_PAGE_ACCESS_TOKEN=<facebook-page-access-token>
```

Do not replace these with old Instagram Login variables like:

```dotenv
EXAMPLE_CREATOR_INSTAGRAM_USER_ACCESS_TOKEN=<do-not-use-for-this-repo>
```

This repo expects Page-token credentials through `Settings.get_meta_credentials()`.

## Step 12: Interpret The Helper Output

Success output should include:

```text
Updated .env with Meta credentials for example_creator.
Facebook Page: Example Creator (<facebook-page-id>)
Instagram business account ID: <instagram-account-id>
Page token expires_at: 0 (non-expiring)
Page token was written to .env and was not printed.
```

`expires_at: 0` is the target result.

If `data_access_expires_at` appears, record the date operationally. It is separate
from the Page token's `expires_at`, but Meta can still require reauthorization if
data access expires or the user/app relationship changes.

## Step 13: Runtime Publishing Context

The token generation app and publishing runtime are related but not identical.

The Meta app is used to create/exchange tokens. The Python publisher later uses
only these values:

```text
Facebook Page ID
Instagram business account ID
Facebook Page access token
```

Each profile can use a Page token generated through its profile-specific app, or
multiple profiles can use tokens generated through a central app when the
controlling Facebook user has access to every required Page.

Rate-limit and enforcement risk can apply at multiple layers:

```text
Meta app
Facebook Page
Instagram business account
User/token
Endpoint/use case
```

Using one app per influencer can isolate app-level issues, but it does not bypass
Page-level or Instagram-account-level limits.

## Troubleshooting

### Graph API Explorer says no apps are available

Cause:

```text
The logged-in Facebook personal account is not assigned to any Meta Developer app.
```

Fix:

```text
Create a Meta app while logged in as that Facebook user, or add that Facebook personal account to an existing app role.
```

### Adding the controlling user to a shared app fails

Likely causes:

```text
You entered the Page ID instead of the Facebook personal user.
The Facebook personal account is not registered as a developer account.
Meta cannot find the user by the identifier entered.
The selected role is too high or blocked by Business settings.
```

Practical fix:

```text
Use a profile-specific Meta app instead of adding the controlling user to the shared app.
```

### `instagram_basic` or `instagram_content_publish` is missing

Likely cause:

```text
The app is configured for the wrong Instagram API product or only the Instagram Login flow.
```

Fix:

```text
Add/configure Instagram API with Facebook Login, Instagram Graph API, and Facebook Login for Business/Facebook Login.
```

### `/me/accounts` does not show Example Creator

Likely causes:

```text
The token-generating Facebook user does not have full Page control.
The Page asset was not selected in the auth popup.
The wrong Facebook account generated the token.
The wrong Meta app/user pairing was used.
```

Fix:

```text
Try direct Page lookup with `<facebook-page-id>?fields=id,name,access_token,instagram_business_account`. If it returns the Page access token and Instagram business account, rerun the helper; it has the same fallback. If direct lookup also fails, regenerate the short-lived User token with the correct user, app, permissions, and selected Page asset.
```

If the Page is missing because it was created after the app was first authorized,
see the next section instead. That is the common case for a new profile.

### Helper fails with "Meta response did not include Page access token"

This is the expected failure when adding a new profile to an app that was already
authorized for an earlier profile. The helper log looks like this:

```text
Looking for Facebook Page ID <new-page-id> in 1 visible page(s).
Page <new-page-id> was not returned by /me/accounts; trying direct Page lookup.
Error: Meta response did not include Page access token.
```

Read it carefully, because it is more informative than it looks:

```text
/me/accounts returned only the previously granted Page, not the new one.
Direct Page lookup succeeded, and the helper's ID match check passed,
so the configured Page ID is correct and the Page exists.
The payload had no access_token, because Meta only returns that field
to a token with admin rights on the Page.
```

Cause: a Facebook user access token carries a per-Page asset grant. A Page created
after the app was authorized is not added to that grant automatically, so the new
Page stays invisible to the token even though the same user administers it.

Fix, without revoking anything:

```text
1. Open facebook.com/settings -> Business Integrations.
2. Open the Meta app's entry and edit which Pages it may access.
3. Tick the new profile's Page and save.
4. Generate a fresh short-lived User token in Graph API Explorer.
5. Confirm me/accounts?fields=name,id,instagram_business_account now lists both Pages.
6. Rerun the helper.
```

Do not remove the app authorization to force the asset picker to reappear. That
works, but it drops the existing grants and makes you reauthorize every previously
working Page. Editing the existing authorization is the safe path.

If the new Page does not appear as a tickable option in Business Integrations, the
token-generating user does not administer it. Add that user with full control in
Business Suite under Settings -> Pages -> the Page -> People, then start over.

The helper is safe to rerun: it fails before `update_env_file()`, so a failed run
never touches `.env`.

### `/me/accounts` shows the Page but no Instagram business account

Likely causes:

```text
Instagram account is not professional.
Instagram account is not linked to the Facebook Page.
The Page is linked to a different Instagram account.
The token lacks instagram_basic.
```

Fix:

```text
Repair the Page to Instagram link in Meta Business Suite and regenerate the user token.
```

### Helper says the Page token is invalid

Likely causes:

```text
Short-lived token expired.
App secret is wrong or was rotated.
The wrong app ID/app secret pair was used.
Meta debug_token did not return is_valid=true.
```

Fix:

```text
Generate a fresh short-lived User token, confirm the app ID/secret pair, and rerun the helper.
```

### The profile's account email is unreachable

Symptom:

```text
The Meta assets still exist, but account recovery emails go to a mailbox or
forwarding domain that no longer resolves, so the account cannot be recovered.
```

First, check whether the mailbox itself is recoverable. If a lapsed domain is the
cause, look up its registry status before assuming it is gone:

```bash
curl -s "https://rdap.verisign.com/com/v1/domain/<domain>.com" | python3 -m json.tool
```

A `redemption period` status means it can still be restored, through the original
registrar only, for a restore fee, and only for about 30 days from the date the
status was set. After that it goes to `pendingDelete` and is released.

If the mailbox cannot be recovered, the Facebook Page and Instagram account are
permanently lost. There is no Meta support path that recovers an account without
email access. Rebuild the profile from Step 1, and note two consequences:

```text
The old Instagram @username stays taken and cannot be freed. Pick a variant.
The old Facebook Page stays published and orphaned. It cannot be deleted.
```

Then replace the profile's dead `.env` keys with the new values from the helper.

### Helper writes `.env`, but publishing still fails

Check:

```text
The runtime loads the repository root .env.
The profile alias maps to EXAMPLE_CREATOR.
EXAMPLE_CREATOR_FACEBOOK_PAGE_ID exists.
EXAMPLE_CREATOR_INSTAGRAM_ACCOUNT_ID exists.
EXAMPLE_CREATOR_FACEBOOK_PAGE_ACCESS_TOKEN exists.
Shared FACEBOOK_STAGING_PAGE_ID and FACEBOOK_STAGING_PAGE_ACCESS_TOKEN also exist for media staging.
```

Do not run live publishing or token validation commands from automation without
explicit approval, because they touch external Meta services.

## Repeat Checklist For A New Influencer

1. Set the controlling email to a mailbox you own directly, and harden recovery on the controlling Facebook account per Step 1.
2. Create the Facebook Page.
3. Create the Instagram account in Meta Business Suite or through Instagram.
4. If created through Instagram, convert it to Creator or Business.
5. Link Instagram to the Facebook Page in Meta Business Suite.
6. Confirm the controlling Facebook user has full Page control.
7. Create or choose the Meta Developer app.
8. Add the Facebook Login based Instagram API product surface.
9. Open Graph API Explorer with the correct app and Graph API version.
10. Add `pages_show_list`, `pages_read_engagement`, `instagram_basic`, and `instagram_content_publish`.
11. If reusing an app already authorized for another profile, tick the new Page under `facebook.com/settings` -> Business Integrations first.
12. Generate a short-lived User token.
13. Confirm `me/accounts?fields=name,id,instagram_business_account` returns the Page and IG business account, or confirm direct `/{page_id}?fields=id,name,access_token,instagram_business_account` returns the Page token and IG business account.
14. Fill in `GRAPH_API_BASE_URL`, `DEFAULT_PROFILE_ALIAS`, `DEFAULT_PAGE_ID`, and `META_APP_ID` inside the script's `if __name__ == "__main__"` block, then run it directly.
15. Confirm helper output reports `expires_at: 0 (non-expiring)`.
16. Confirm `.env` has `{PROFILE}_FACEBOOK_PAGE_ID`, `{PROFILE}_INSTAGRAM_ACCOUNT_ID`, and `{PROFILE}_FACEBOOK_PAGE_ACCESS_TOKEN`.
17. Keep app secret and tokens in `.env` or a password manager only.

## Commands

Example Creator helper setup inside the `if __name__ == "__main__"` block:

```python
GRAPH_API_BASE_URL = "https://graph.facebook.com/v25.0"
DEFAULT_PROFILE_ALIAS = "example_creator"
DEFAULT_PAGE_ID = "<facebook-page-id>"
META_APP_ID = "<meta-app-id>"
```

Helper command from the repository root:

```bash
uv run python apps/ai-content-pipeline/scripts/exchange_meta_page_token.py
```

Focused tests for the helper:

```bash
uv run pytest apps/ai-content-pipeline/tests/test_exchange_meta_page_token_script.py -q
```

Full local verification:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q
uv run pre-commit run --all-files
```
