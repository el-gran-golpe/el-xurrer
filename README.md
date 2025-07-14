# El Xurrer

*A modular, end‑to‑end pipeline for **planning, generating, scheduling,** and **posting** AI‑powered multimedia content to social platforms.*

![logo](assets/el_xurrer_logo.png) <!-- optional illustration -->

---

## ✨ Key Features

* **Multi‑platform support** – ready‑made service wrappers for Meta Graph (Instagram/Facebook), YouTube, and Fanvue, with a clean interface for adding others.
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

### 3 · Configure credentials

Create a `.env` file (or export variables):

```dotenv
# Meta Graph API
META_ACCESS_TOKEN=EAAB...

# YouTube Data v3
YOUTUBE_CLIENT_SECRETS=./secrets/client_secrets.json
YOUTUBE_REFRESH_TOKEN=...

# OpenAI / Replicate / etc.
OPENAI_API_KEY=sk‑...

# Optional: WandB experiment tracking
WANDB_API_KEY=...
```

---

## 🚀 Usage

### Generate & post to Instagram/Facebook

```bash
python mains/main_meta.py --plan --generate --upload
```

### Generate assets only (no upload)

```bash
python mains/main_meta.py --plan --generate
```

### Command‑line flags

| Flag         | Action                                                  |
| ------------ | ------------------------------------------------------- |
| `--plan`     | Build (or refresh) the content calendar                 |
| `--generate` | Create images / videos / captions according to the plan |
| `--upload`   | Schedule or immediately post content via platform APIs  |

---

## 🗂️ Repository Overview

| Path                          | Purpose                                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- |
| **`main_components/`**        | High‑level orchestration: `planning_manager.py`, `publications_generator.py`, `posting_scheduler.py`, … |
| **`generation_tools/`**       | Low‑level media creation: `image_generator/`, `voice_generator/`, `thumbnails_generator/`, …            |
| **`bot_services/`**           | Thin API clients for Meta, YouTube, Fanvue; handles auth, retries, rate‑limits                          |
| **`llm/`**                    | Base and platform‑specific LLM helpers (`meta_llm.py`, `fanvue_llm.py`)                                 |
| **`mains/`**                  | CLI entry points (`main_meta.py`, `main_fanvue.py`, etc.)                                               |
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
