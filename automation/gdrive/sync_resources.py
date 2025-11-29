from pathlib import Path
import io
import pickle
import hashlib
from typing import Optional
from tqdm import tqdm

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from loguru import logger
from pydantic_settings import BaseSettings
from pydantic import field_validator

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError


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

    def __init__(self, settings: Optional[GDriveSettings] = None):
        self.settings = settings or GDriveSettings()
        self.token_path = self.settings.token_path.expanduser()
        self.folder_id = self.settings.folder_id
        logger.info(
            "Initialized {} for Google Drive folder with id {}",
            self.__class__.__name__,
            self.folder_id,
        )

    def pull(self, dest: Path) -> None:
        """Download entire Drive folder to local path."""
        service = self._get_drive_service()
        dest = dest.expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        self._download_folder(service, self.folder_id, dest)
        logger.success("Google Drive → Local sync complete: {}", dest)

    def push(self, src: Path) -> None:
        """Upload/update all files under local path to Drive folder, preserving structure."""
        service = self._get_drive_service()
        src = src.expanduser()
        self._upload_folder(service, src, self.folder_id)
        logger.success("Local → Google Drive sync complete: {}", src)

    # TODO: check that this has no vulnerabilities
    def _get_drive_service(self):
        """Authenticate (or load cached token), auto-refresh if expired, and return Drive v3 client."""
        creds = None
        try:
            # Load cached credentials if present
            if self.token_path.exists():
                with open(self.token_path, "rb") as f:
                    creds = pickle.load(f)

            # If no creds or invalid, try to refresh; otherwise do interactive auth
            if not creds or not creds.valid:
                if creds and creds.expired and getattr(creds, "refresh_token", None):
                    try:
                        creds.refresh(
                            Request()
                        )  # auto-renews access token using the refresh token
                        logger.debug("Refreshed access token")
                    except RefreshError:
                        logger.warning("Token refresh failed; falling back to re-auth")
                        creds = None  # force re-auth below

                if not creds or not creds.valid:
                    # Build an InstalledApp flow (OOB is deprecated—use localhost redirect)
                    config = {
                        "installed": {
                            "client_id": self.settings.client_id,
                            "client_secret": self.settings.client_secret,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": [
                                "http://localhost"
                            ],  # no 'urn:ietf:wg:oauth2:2.0:oob'
                        }
                    }
                    flow = InstalledAppFlow.from_client_config(config, self.SCOPES)
                    # This opens a browser once; tokens (incl. refresh_token) are saved to disk
                    creds = flow.run_local_server(port=0)

            # Persist (new or refreshed) credentials
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "wb") as f:
                pickle.dump(creds, f)

            return build("drive", "v3", credentials=creds)

        except Exception:
            logger.exception("Failed to obtain Drive service")
            raise

    def _upload_folder(self, service, local_path: Path, drive_folder_id: str) -> None:
        """Recursively upload a local folder to the corresponding Drive folder."""
        files = [f for f in local_path.rglob("*") if f.is_file()]
        for file_path in tqdm(files, desc="Uploading files", unit="file"):
            rel_parent = file_path.parent.relative_to(local_path)
            parent_id = drive_folder_id
            for part in rel_parent.parts:
                parent_id = self._get_or_create_drive_folder(service, part, parent_id)
            updated = self._upload_file(service, file_path, parent_id)
            if updated:
                # Replaced existing remote file (yellow)
                logger.warning("Overwrote file on Drive: {}", file_path)
            else:
                # Uploaded new remote file (green)
                logger.success("Uploaded new file to Drive: {}", file_path)

    def _get_or_create_drive_folder(
        self, service, folder_name: str, parent_id: str
    ) -> str:
        query = (
            f"'{parent_id}' in parents and name = '{folder_name}' and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        resp = service.files().list(q=query, fields="files(id)").execute()
        files = resp.get("files", [])
        if files:
            return files[0]["id"]
        folder = (
            service.files()
            .create(
                body={
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
                fields="id",
            )
            .execute()
        )
        logger.success(
            "Created new remote folder: '{}' (id={})", folder_name, folder["id"]
        )
        return folder["id"]

    def _upload_file(self, service, file_path: Path, parent_id: str) -> bool:
        name = file_path.name
        query = f"'{parent_id}' in parents and name = '{name}' and trashed = false"
        resp = service.files().list(q=query, fields="files(id)").execute()
        files = resp.get("files", [])
        media = MediaFileUpload(str(file_path), resumable=True)
        if files:
            service.files().update(fileId=files[0]["id"], media_body=media).execute()
            return True
        service.files().create(
            body={"name": name, "parents": [parent_id]}, media_body=media
        ).execute()
        return False

    def _download_folder(self, service, drive_folder_id: str, local_path: Path) -> None:
        files_to_download = []

        def collect_files(folder_id, path):
            query = f"'{folder_id}' in parents and trashed = false"
            resp = (
                service.files()
                .list(q=query, fields="files(id,name,mimeType)")
                .execute()
            )
            for item in resp.get("files", []):
                fid, name, mime = item["id"], item["name"], item["mimeType"]
                target = path / name
                if mime == "application/vnd.google-apps.folder":
                    collect_files(fid, target)
                else:
                    files_to_download.append((fid, target))

        collect_files(drive_folder_id, local_path)
        with tqdm(
            total=len(files_to_download), desc="Synchronizing files", unit="file"
        ) as pbar:
            for fid, target in files_to_download:
                if target.exists():
                    remote_bytes = self._download_file_to_bytes(service, fid)
                    if self._file_contents_equal(target, remote_bytes):
                        pbar.update(1)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("wb") as out_f:
                        out_f.write(remote_bytes)
                    # Replaced existing local file (yellow)
                    logger.warning(
                        "Replaced local file with updated version: {}", target
                    )
                else:
                    self._download_file(service, fid, target)
                    # Downloaded new local file (green)
                    logger.success("Downloaded new file to local: {}", target)
                pbar.update(1)

    def _download_file(self, service, file_id: str, target: Path) -> None:
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
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()

    def _file_contents_equal(self, local_path: Path, remote_bytes: bytes) -> bool:
        local_hash = hashlib.md5(local_path.read_bytes()).digest()
        remote_hash = hashlib.md5(remote_bytes).digest()
        return local_hash == remote_hash
