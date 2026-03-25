![logo](assets/el_xurrer_logo.png) <!-- optional illustration -->

El-xurrer is a modular, end‑to‑end pipeline for planning, generating, scheduling, and posting AI‑powered multimedia content to social platforms.

---

## ✨ Key Features

* **Instagram-first publishing** - plan, generate, and publish Instagram posts with Instagram Login, using shared Facebook media staging only to generate zero-dollar public asset URLs before continuing the pipeline into Fanvue.
* **Generative tooling** – image (Stable Diffusion via 🤗 Diffusers), video and thumbnail synthesis, TTS voice‑overs, background music, and automatic captions.
* **LLM‑driven creativity** – prompt engineering helpers and templates to turn high‑level campaign ideas into publish‑ready assets.
* **Automated workflow** – plan editorial calendars, batch‑generate assets, and schedule uploads, all from simple CLI commands or cron.
* **Production‑ready** – Dockerfile, pre‑commit hooks, typed codebase (mypy), granular logging with *loguru*, and optional Weights & Biases monitoring.

---

## ⏳ Quick Start

### 1 · Prerequisites

| Requirement                  | Notes                                       |
| ---------------------------- | ------------------------------------------- |
| **Python 3.10+**             | Recommended to use a virtual env            |
| **ffmpeg** / **ImageMagick** | Needed for video/audio and image processing |
| NVIDIA GPU (optional)        | Speeds‑up diffusion models                  |

### 2 · Install

```bash
git clone https://github.com/your‑org/el‑xurrer.git
cd el‑xurrer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pre-commit install          # run code‑quality hooks on every commit
```

### 3 · Configure Instagram Login and shared media staging

Create a `.env` file (or export variables):

```dotenv
# Required shared services
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=...
client_id=...
client_secret=...
folder_id=...

# Per-profile Instagram Login credentials
LAURA_VIGNE_INSTAGRAM_ACCOUNT_ID=1784...
LAURA_VIGNE_INSTAGRAM_USER_ACCESS_TOKEN=...
MARIA_LARSEN_INSTAGRAM_ACCOUNT_ID=1784...
MARIA_LARSEN_INSTAGRAM_USER_ACCESS_TOKEN=...

# Shared Facebook staging page used only to generate public media URLs for
# Instagram publishing. This repo does not use it for Facebook cross-posting.
# Use a direct Page access token for the staging Page.
FACEBOOK_STAGING_PAGE_ID=
FACEBOOK_STAGING_PAGE_ACCESS_TOKEN=
```

The posting path is now Instagram-only via Instagram Login. Facebook remains in
the runtime solely as a zero-dollar media staging helper because Instagram
publishing still needs a public `image_url` for each asset.

The staging helper no longer uses a short-lived Facebook user token. It now
expects a direct `FACEBOOK_STAGING_PAGE_ACCESS_TOKEN`, which is a better match
for this automation flow because the runtime only stages media on one known
Page and does not need to discover a Page token through `/me/accounts`.

This change removes the old `FACEBOOK_STAGING_USER_ACCESS_TOKEN` contract from
the repo. In practice, the goal is a hands-off token setup for the staging
Page. "Immortal" here should be understood operationally, not literally: the
token is intended to avoid time-based refresh churn, but it can still be
invalidated if Meta app access, business assets, page permissions, or assigned
roles change.

Migration summary:

- old: `FACEBOOK_STAGING_USER_ACCESS_TOKEN`
- new: `FACEBOOK_STAGING_PAGE_ACCESS_TOKEN`
- behavior change: the staging helper now uses the configured Page token
  directly and no longer performs a `/me/accounts` lookup at runtime

---

## 🚀 Usage

### Run the Instagram posting pipeline

```bash
python main.py meta plan -p 0
python main.py meta generate -p 0
python main.py meta schedule -p 0
```

### Run the full Instagram -> Fanvue pipeline

```bash
python main.py all run_all -p 0
```

### Instagram credential model

For each migrated influencer profile you need:

- `<PROFILE>_INSTAGRAM_ACCOUNT_ID`
- `<PROFILE>_INSTAGRAM_USER_ACCESS_TOKEN`

For the shared zero-dollar media staging helper you need:

- `FACEBOOK_STAGING_PAGE_ID`
- `FACEBOOK_STAGING_PAGE_ACCESS_TOKEN`

---

## 🗂️ Repository Overview

| Path                          | Purpose                                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- |
| **`main_components/`**        | High‑level orchestration: `planning_manager.py`, `publications_generator.py`, `posting_scheduler.py`, … |
| **`generation_tools/`**       | Low‑level media creation: `image_generator/`, `voice_generator/`, `thumbnails_generator/`, …            |
| **`bot_services/`**           | Thin API clients for Meta, YouTube, Fanvue; handles auth, retries, rate‑limits                          |
| **`llm/`**                    | Base and platform‑specific LLM helpers (`meta_llm.py`, `fanvue_llm.py`)                                 |
| **`mains/`**                  | CLI command modules used by [`main.py`](main.py) for Instagram publishing and Fanvue workflows          |
| **`utils/`**                  | Shared helpers, custom exceptions, lightweight HTTP server                                              |
| **`Dockerfile`**              | Build reproducible containers                                                                           |
| **`.pre-commit-config.yaml`** | Black, isort, flake8, mypy, etc.                                                                        |

---

## 🤝 Contributing

1. Fork & branch off `main`.
2. Ensure `pre‑commit` passes (`black`, `isort`, `flake8`, `mypy`).
3. Open a pull request describing *why* and *how*.

We love issues & feature requests—feel free to open a discussion!

---

## 📜 License

[MIT](LICENSE) © 2025 The El Xurrer Contributors

---

<details>
<summary>📚 Legacy README (for historical reference)</summary>

# La màquina de fer xurros

### OS Independent

#### Install pre-commit:

```bash
pip install pre-commit
pre-commit install
```

With this, pre-commit will run before every commit, checking for code style and formatting.

For specific information check the `.pre-commit-config.yaml` file.

### Windows

#### Install ffmpeg:

Run terminal as administrator
...

#### Install ImageMagick:

[https://imagemagick.org/archive/binaries](https://imagemagick.org/archive/binaries) #/ImageMagick-6.9.13-16-Q16-HDRI-x64-dll.exe

pip install imageio\[ffmpeg]

pip install git+[https://github.com/jpgallegoar/Spanish-F5.git](https://github.com/jpgallegoar/Spanish-F5.git)

pip install -r .\requirements.txt --ignore-requires-python

</details>
