from pathlib import Path
import io
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from loguru import logger
from pydantic import BaseSettings, field_validator


class GDriveSettings(BaseSettings):
    """Load sensitive paths from gdrive.env"""

    credentials_path: Path
    token_path: Path

    @field_validator("credentials_path")
    @classmethod
    def validate_credentials_path(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"Credentials file not found at '{v}'")
        return v

    class Config:
        env_file = "gdrive.env"
        env_file_encoding = "utf-8"


class GoogleDriveSync:
    """
    Sync local <-> Google Drive folder contents.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self, settings: GDriveSettings):
        self.settings = settings or GDriveSettings()
        self.credentials_path = self.settings.credentials_path.expanduser()
        self.token_path = self.settings.token_path.expanduser()
        logger.debug(
            "Initialized {} with credentials at {} and token at {}",
            self.__class__.__name__,
            self.credentials_path,
            self.token_path,
        )

    def pull(self, folder_id: str, dest: Path) -> None:
        service = self._get_drive_service()
        dest = dest.expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        self._download_folder(service, folder_id, dest)
        logger.success("Drive → local sync complete: {}", dest)

    def push(self, folder_id: str, src: Path) -> None:
        """
        Upload all files from local `src` into Drive folder `folder_id`,
        creating or updating. Does not delete remote files.
        """
        service = self._get_drive_service()
        src = src.expanduser()
        query = f"'{folder_id}' in parents and trashed = false"
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
                    body={"name": name, "parents": [folder_id]}, media_body=media
                ).execute()

        logger.success("Local→Drive sync complete: {}", src)

    def _get_drive_service(self):
        """Authenticate (or load cached token) and return a Drive v3 service client."""
        creds = None
        try:
            if self.token_path.exists():
                with open(self.token_path, "rb") as f:
                    creds = pickle.load(f)
                logger.debug("Loaded cached credentials from {}", self.token_path)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), self.SCOPES
                )
                creds = flow.run_local_server(port=0)
                self.token_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.token_path, "wb") as f:
                    pickle.dump(creds, f)
                logger.debug("Saved new token to {}", self.token_path)
            return build("drive", "v3", credentials=creds)
        except Exception:
            logger.exception("Failed to get Drive service")
            raise

    def _download_folder(self, service, drive_folder_id: str, local_path: Path) -> None:
        query = f"'{drive_folder_id}' in parents and trashed = false"
        resp = service.files().list(q=query, fields="files(id,name,mimeType)").execute()
        for item in resp.get("files", []):
            file_id = item["id"]
            name = item["name"]
            mime = item["mimeType"]
            target = local_path / name
            if mime == "application/vnd.google-apps.folder":
                self._download_folder(service, file_id, target)
            else:
                self._download_file(file_id, target)
                logger.info("Downloaded {}", target)

    def _download_file(self, file_id: str, target: Path) -> None:
        """Download a single file into `target`."""
        request = self._get_drive_service().files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as out_f:
            out_f.write(fh.getvalue())
