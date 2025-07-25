from pathlib import Path
import io
import pickle
import hashlib
from typing import Optional

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from loguru import logger
from pydantic_settings import BaseSettings
from pydantic import field_validator


class GDriveSettings(BaseSettings):
    client_id: str
    client_secret: str
    token_path: Path = Path.home() / ".config/myapp/token.pickle"
    folder_id: str

    @field_validator("client_id", "client_secret", "folder_id")
    @classmethod
    def not_empty(cls, v: str, field) -> str:
        if not v:
            raise ValueError(f"{field.name} must not be empty")
        return v

    class Config:
        env_file = Path(__file__).parent / "gdrive.env"
        env_file_encoding = "utf-8"


class GoogleDriveSync:
    """
    Sync local <-> Google Drive folder contents using env-configured folder ID.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self, settings: Optional[GDriveSettings]):
        self.settings = settings or GDriveSettings()
        self.token_path = self.settings.token_path.expanduser()
        self.folder_id = self.settings.folder_id
        logger.debug(
            "Initialized {} for Drive folder {}",
            self.__class__.__name__,
            self.folder_id,
        )

    def pull(self, dest: Path) -> None:
        """Download entire Drive folder to local path."""
        service = self._get_drive_service()
        dest = dest.expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        self._download_folder(service, self.folder_id, dest)
        logger.success("Drive → local sync complete: {}", dest)

    def push(self, src: Path) -> None:
        """Upload/update all files under local path to Drive folder."""
        service = self._get_drive_service()
        src = src.expanduser()

        query = f"'{self.folder_id}' in parents and trashed = false"
        resp = service.files().list(q=query, fields="files(id,name)").execute()
        remote_map = {item["name"]: item["id"] for item in resp.get("files", [])}

        for path in src.rglob("*"):
            if not path.is_file():
                continue
            name = path.name
            media = MediaFileUpload(str(path), resumable=True)
            if name in remote_map:
                logger.info("Updating remote file {}", name)
                service.files().update(
                    fileId=remote_map[name], media_body=media
                ).execute()
            else:
                logger.info("Uploading new file {}", name)
                service.files().create(
                    body={"name": name, "parents": [self.folder_id]}, media_body=media
                ).execute()

        logger.success("Local→Drive sync complete: {}", src)

    def _get_drive_service(self):
        """Authenticate (or load cached token) and return Drive v3 client."""
        creds = None
        try:
            if self.token_path.exists():
                with open(self.token_path, "rb") as f:
                    creds = pickle.load(f)
                logger.debug("Loaded cached credentials from {}", self.token_path)
            else:
                config = {
                    "installed": {
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [
                            "urn:ietf:wg:oauth:2.0:oob",
                            "http://localhost",
                        ],
                    }
                }
                flow = InstalledAppFlow.from_client_config(config, self.SCOPES)
                creds = flow.run_local_server(port=0)
                self.token_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.token_path, "wb") as f:
                    pickle.dump(creds, f)
                logger.debug("Saved new token to {}", self.token_path)
            return build("drive", "v3", credentials=creds)
        except Exception:
            logger.exception("Failed to obtain Drive service")
            raise

    def _download_folder(self, service, drive_folder_id: str, local_path: Path) -> None:
        query = f"'{drive_folder_id}' in parents and trashed = false"
        resp = service.files().list(q=query, fields="files(id,name,mimeType)").execute()
        for item in resp.get("files", []):
            fid = item["id"]
            name = item["name"]
            mime = item["mimeType"]
            target = local_path / name
            if mime == "application/vnd.google-apps.folder":
                self._download_folder(service, fid, target)
            else:
                if target.exists():
                    remote_bytes = self._download_file_to_bytes(service, fid)
                    if self._file_contents_equal(target, remote_bytes):
                        logger.info("Skipping identical file {}", target)
                        continue
                    else:
                        logger.info("Overwriting differing file {}", target)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("wb") as out_f:
                            out_f.write(remote_bytes)
                        logger.info(
                            "\033[93mDownloaded (overwritten)\033[0m {}", target
                        )
                else:
                    self._download_file(service, fid, target)
                    logger.info("Downloaded {}", target)

    def _download_file(self, service, file_id: str, target: Path) -> None:
        """Stream a single Drive file to local path."""
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as out_f:
            out_f.write(fh.getvalue())

    def _download_file_to_bytes(self, service, file_id: str) -> bytes:
        """Download a Drive file and return its bytes."""
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()

    def _file_contents_equal(self, local_path: Path, remote_bytes: bytes) -> bool:
        """Compare local file content with remote bytes using hash."""
        if not local_path.exists():
            return False
        local_hash = hashlib.md5(local_path.read_bytes()).digest()
        remote_hash = hashlib.md5(remote_bytes).digest()
        return local_hash == remote_hash
