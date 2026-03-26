from dataclasses import dataclass
from pathlib import Path
import hashlib
import io

from tqdm import tqdm

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from loguru import logger

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

from main_components.common.profile import ProfileManager
from main_components.common.types import Platform
from main_components.config import settings


@dataclass(frozen=True)
class RemoteFolder:
    id: str
    path: Path
    name: str
    parent_id: str


@dataclass(frozen=True)
class RemoteFile:
    id: str
    path: Path
    name: str
    parent_id: str
    md5_checksum: str | None


@dataclass(frozen=True)
class RemoteIndex:
    folders: dict[Path, RemoteFolder]
    files: dict[Path, RemoteFile]


class GoogleDriveSync:
    """
    Sync the Google Drive source of truth for profile resources.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive"]
    FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
    INITIAL_CONDITIONS_FILENAME = "initial_conditions.md"

    def __init__(self):
        self.settings = settings
        self.token_path = Path.home() / ".config/myapp/token.json"
        self.folder_id = self.settings.folder_id
        logger.info(
            "Initialized {} for Google Drive folder with id {}",
            self.__class__.__name__,
            self.folder_id,
        )

    def pull(self, dest: Path) -> None:
        """Download the validated managed files from Drive into the local resources root."""
        service = self._get_drive_service()
        dest = dest.expanduser()
        dest.mkdir(parents=True, exist_ok=True)

        remote_index = self._build_remote_index(service, self.folder_id)
        remote_manifest = self._build_remote_pull_manifest(remote_index)
        self._pull_manifest(service, dest, remote_manifest)

        logger.success("Google Drive → Local sync complete: {}", dest)

    def push(self, src: Path) -> None:
        """Upload the validated managed files from the local resources root to Drive."""
        service = self._get_drive_service()
        src = src.expanduser()

        local_manifest = self._build_local_manifest(src)
        remote_index = self._build_remote_index(service, self.folder_id)
        self._push_manifest(service, local_manifest, remote_index)

        logger.success("Local → Google Drive sync complete: {}", src)

    # TODO: check that this has no vulnerabilities
    def _get_drive_service(self):
        """Authenticate (or load cached token), auto-refresh if expired, and return Drive v3 client."""
        try:
            creds = self._load_cached_credentials()

            if not creds or not creds.valid:
                if creds and creds.expired and getattr(creds, "refresh_token", None):
                    try:
                        creds.refresh(Request())
                        logger.debug("Refreshed access token")
                    except RefreshError:
                        logger.warning("Token refresh failed; falling back to re-auth")
                        creds = None

                if not creds or not creds.valid:
                    config = {
                        "installed": {
                            "client_id": self.settings.client_id,
                            "client_secret": self.settings.client_secret,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": ["http://localhost"],
                        }
                    }
                    flow = InstalledAppFlow.from_client_config(config, self.SCOPES)
                    creds = flow.run_local_server(port=0)

            self._save_credentials(creds)

            return build("drive", "v3", credentials=creds)

        except Exception:
            logger.exception("Failed to obtain Drive service")
            raise

    def _load_cached_credentials(self):
        if not self.token_path.exists():
            return None

        try:
            return Credentials.from_authorized_user_file(
                str(self.token_path),
                self.SCOPES,
            )
        except Exception:
            logger.warning(
                "Failed to load cached credentials from {}. Re-authentication required.",
                self.token_path,
            )
            return None

    def _save_credentials(self, creds) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def _build_local_manifest(self, root: Path) -> dict[Path, Path]:
        if not root.is_dir():
            raise FileNotFoundError(f"Resource directory not found: {root}")

        manifest: dict[Path, Path] = {}
        profile_dirs = sorted(child for child in root.iterdir() if child.is_dir())

        for profile_dir in profile_dirs:
            if not self._is_valid_profile_name(profile_dir.name):
                raise ValueError(f"Invalid profile directory name: {profile_dir.name}")
            manifest.update(self._validate_local_profile(root, profile_dir))

        return manifest

    def _validate_local_profile(
        self, root: Path, profile_dir: Path
    ) -> dict[Path, Path]:
        profile_name = profile_dir.name
        manifest: dict[Path, Path] = {}

        workflow_path = profile_dir / f"{profile_name}{ProfileManager.WORKFLOW_SUFFIX}"
        if not workflow_path.is_file():
            raise ValueError(f"Missing workflow JSON: {workflow_path}")
        manifest[workflow_path.relative_to(root)] = workflow_path

        for platform in Platform:
            platform_dir = profile_dir / platform
            if not platform_dir.is_dir():
                raise ValueError(f"Missing platform directory: {platform_dir}")

            inputs_dir = platform_dir / "inputs"
            if not inputs_dir.is_dir():
                raise ValueError(f"Missing inputs directory: {inputs_dir}")

            expected_names = {
                self.INITIAL_CONDITIONS_FILENAME,
                f"{profile_name}.json",
            }
            entries = sorted(inputs_dir.iterdir())
            actual_names = {entry.name for entry in entries if entry.is_file()}

            if len(entries) != 2 or any(entry.is_dir() for entry in entries):
                raise ValueError(
                    f"{inputs_dir} must contain exactly 2 files named "
                    f"{sorted(expected_names)}"
                )
            if actual_names != expected_names:
                raise ValueError(
                    f"{inputs_dir} must contain exactly 2 files named "
                    f"{sorted(expected_names)}"
                )

            for file_name in sorted(expected_names):
                file_path = inputs_dir / file_name
                if not file_path.is_file():
                    raise ValueError(f"Missing required input file: {file_path}")
                manifest[file_path.relative_to(root)] = file_path

        return manifest

    def _build_remote_pull_manifest(
        self, remote_index: RemoteIndex
    ) -> dict[Path, RemoteFile]:
        manifest: dict[Path, RemoteFile] = {}
        for profile_name in self._iter_remote_profile_names(remote_index):
            manifest.update(self._validate_remote_profile(remote_index, profile_name))
        return manifest

    def _iter_remote_profile_names(self, remote_index: RemoteIndex) -> list[str]:
        return sorted(
            {
                path.name
                for path in remote_index.folders
                if len(path.parts) == 1 and self._is_valid_profile_name(path.name)
            }
        )

    def _validate_remote_profile(
        self, remote_index: RemoteIndex, profile_name: str
    ) -> dict[Path, RemoteFile]:
        manifest: dict[Path, RemoteFile] = {}
        profile_root = Path(profile_name)
        workflow_path = profile_root / f"{profile_name}{ProfileManager.WORKFLOW_SUFFIX}"

        workflow_file = remote_index.files.get(workflow_path)
        if workflow_file is None:
            raise ValueError(f"Missing workflow JSON on Drive: {workflow_path}")
        manifest[workflow_path] = workflow_file

        for platform in Platform:
            platform_path = profile_root / platform
            inputs_path = platform_path / "inputs"

            if platform_path not in remote_index.folders:
                raise ValueError(
                    f"Missing platform directory on Drive: {platform_path}"
                )
            if inputs_path not in remote_index.folders:
                raise ValueError(f"Missing inputs directory on Drive: {inputs_path}")

            nested_folders = [
                folder_path
                for folder_path in remote_index.folders
                if len(folder_path.parts) > len(inputs_path.parts)
                and folder_path.parts[: len(inputs_path.parts)] == inputs_path.parts
            ]
            nested_files = [
                file_path
                for file_path in remote_index.files
                if len(file_path.parts) > len(inputs_path.parts) + 1
                and file_path.parts[: len(inputs_path.parts)] == inputs_path.parts
            ]
            if nested_folders or nested_files:
                raise ValueError(f"Drive inputs directory must be flat: {inputs_path}")

            expected_names = {
                self.INITIAL_CONDITIONS_FILENAME,
                f"{profile_name}.json",
            }
            direct_files = {
                file_path.name: remote_file
                for file_path, remote_file in remote_index.files.items()
                if file_path.parent == inputs_path
            }

            if len(direct_files) != 2 or set(direct_files) != expected_names:
                raise ValueError(
                    f"Drive inputs directory {inputs_path} must contain exactly 2 files named "
                    f"{sorted(expected_names)}"
                )

            for file_name in sorted(expected_names):
                manifest[inputs_path / file_name] = direct_files[file_name]

        return manifest

    def _build_remote_index(self, service, drive_folder_id: str) -> RemoteIndex:
        folders: dict[Path, RemoteFolder] = {}
        files: dict[Path, RemoteFile] = {}
        pending = [(Path(), drive_folder_id)]

        while pending:
            current_path, current_id = pending.pop()
            for item in self._list_drive_children(service, current_id):
                item_path = current_path / item["name"]
                if item_path in folders or item_path in files:
                    raise ValueError(f"Duplicate remote path detected: {item_path}")

                if item["mimeType"] == self.FOLDER_MIME_TYPE:
                    folder = RemoteFolder(
                        id=item["id"],
                        path=item_path,
                        name=item["name"],
                        parent_id=current_id,
                    )
                    folders[item_path] = folder
                    pending.append((item_path, folder.id))
                else:
                    files[item_path] = RemoteFile(
                        id=item["id"],
                        path=item_path,
                        name=item["name"],
                        parent_id=current_id,
                        md5_checksum=item.get("md5Checksum"),
                    )

        return RemoteIndex(folders=folders, files=files)

    def _list_drive_children(self, service, folder_id: str) -> list[dict]:
        children: list[dict] = []
        page_token = None
        while True:
            response = (
                service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id,name,mimeType,md5Checksum)",
                    pageToken=page_token,
                )
                .execute()
            )
            children.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return children

    def _pull_manifest(
        self, service, dest: Path, remote_manifest: dict[Path, RemoteFile]
    ) -> None:
        downloads: list[tuple[RemoteFile, Path]] = []

        for rel_path, remote_file in sorted(remote_manifest.items()):
            local_path = dest / rel_path
            if (
                local_path.is_file()
                and remote_file.md5_checksum
                and self._local_md5(local_path) == remote_file.md5_checksum
            ):
                continue
            downloads.append((remote_file, local_path))

        with tqdm(
            total=len(downloads), desc="Pulling managed files", unit="file"
        ) as pbar:
            for remote_file, target in downloads:
                existed = target.exists()
                self._download_file(service, remote_file.id, target)
                if existed:
                    logger.warning("Updated local managed file: {}", target)
                else:
                    logger.success("Downloaded local managed file: {}", target)
                pbar.update(1)

    def _push_manifest(
        self,
        service,
        local_manifest: dict[Path, Path],
        remote_index: RemoteIndex,
    ) -> None:
        local_profile_names = {path.parts[0] for path in local_manifest}
        keep_files = set(local_manifest)
        keep_folders = self._build_required_folder_paths(local_profile_names)

        # Valid profile directories on Drive that are NOT part of this push are
        # preserved in full — their files and folders are never touched.
        # Everything else (including non-profile top-level items such as a 'misc'
        # folder or a root-level file) is treated as deletable if it is not in the
        # sync contract. This is intentional: the configured Drive folder is treated
        # as owned by this tool, so any unrecognised content is cleaned up on push.
        preserved_remote_profiles = {
            path.name
            for path in remote_index.folders
            if len(path.parts) == 1
            and self._is_valid_profile_name(path.name)
            and path.name not in local_profile_names
        }

        # Deleted: any remote file/folder that is not under a preserved profile AND
        # is not part of the expected sync contract (keep_files / keep_folders).
        # This includes stray files at the Drive root, unknown top-level folders,
        # and extra files inside locally-pushed profile directories.
        files_to_delete = [
            remote_file
            for remote_file in remote_index.files.values()
            if remote_file.path.parts[0] not in preserved_remote_profiles
            and remote_file.path not in keep_files
        ]
        folders_to_delete = [
            remote_folder
            for remote_folder in remote_index.folders.values()
            if remote_folder.path.parts[0] not in preserved_remote_profiles
            and remote_folder.path not in keep_folders
        ]

        for stale_file in files_to_delete:
            self._delete_remote_item(service, stale_file.id)
            logger.warning(
                "Deleted remote file outside sync contract: {}", stale_file.path
            )

        # Delete deepest folders first to avoid removing a parent before its children.
        for remote_folder in sorted(
            folders_to_delete,
            key=lambda folder: len(folder.path.parts),
            reverse=True,
        ):
            self._delete_remote_item(service, remote_folder.id)
            logger.warning(
                "Deleted remote folder outside sync contract: {}", remote_folder.path
            )

        folder_cache = {Path(): self.folder_id, Path("."): self.folder_id}
        folder_cache.update(
            {folder.path: folder.id for folder in remote_index.folders.values()}
        )

        uploads: list[tuple[Path, Path, RemoteFile | None]] = []
        for rel_path, local_path in sorted(local_manifest.items()):
            remote_file: RemoteFile | None = remote_index.files.get(rel_path)
            local_md5 = self._local_md5(local_path)
            if remote_file and remote_file.md5_checksum == local_md5:
                continue
            uploads.append((rel_path, local_path, remote_file))

        with tqdm(
            total=len(uploads), desc="Pushing managed files", unit="file"
        ) as pbar:
            for rel_path, local_path, remote_file in uploads:
                parent_id = self._ensure_remote_folder_path(
                    service, folder_cache, rel_path.parent
                )
                if remote_file is None:
                    self._create_remote_file(service, local_path, parent_id)
                    logger.success("Uploaded new file to Drive: {}", rel_path)
                else:
                    self._update_remote_file(service, remote_file.id, local_path)
                    logger.warning("Updated file on Drive: {}", rel_path)
                pbar.update(1)

    def _build_required_folder_paths(self, profile_names: set[str]) -> set[Path]:
        folders: set[Path] = set()
        for profile_name in profile_names:
            profile_path = Path(profile_name)
            folders.add(profile_path)
            for platform in Platform:
                platform_path = profile_path / platform
                folders.add(platform_path)
                folders.add(platform_path / "inputs")
        return folders

    def _ensure_remote_folder_path(
        self,
        service,
        folder_cache: dict[Path, str],
        rel_path: Path,
    ) -> str:
        if rel_path in (Path(), Path(".")):
            return self.folder_id

        current = Path()
        parent_id = self.folder_id
        for part in rel_path.parts:
            if part == ".":
                continue
            current = current / part
            cached_id = folder_cache.get(current)
            if cached_id:
                parent_id = cached_id
                continue

            folder_id = self._create_remote_folder(service, part, parent_id)
            folder_cache[current] = folder_id
            parent_id = folder_id

        return parent_id

    def _create_remote_folder(self, service, folder_name: str, parent_id: str) -> str:
        folder = (
            service.files()
            .create(
                body={
                    "name": folder_name,
                    "mimeType": self.FOLDER_MIME_TYPE,
                    "parents": [parent_id],
                },
                fields="id",
            )
            .execute()
        )
        return folder["id"]

    def _create_remote_file(self, service, file_path: Path, parent_id: str) -> None:
        media = MediaFileUpload(str(file_path), resumable=True)
        service.files().create(
            body={"name": file_path.name, "parents": [parent_id]},
            media_body=media,
        ).execute()

    def _update_remote_file(self, service, file_id: str, file_path: Path) -> None:
        media = MediaFileUpload(str(file_path), resumable=True)
        service.files().update(fileId=file_id, media_body=media).execute()

    def _delete_remote_item(self, service, item_id: str) -> None:
        service.files().delete(fileId=item_id).execute()

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

    def _local_md5(self, file_path: Path) -> str:
        digest = hashlib.md5()
        with file_path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _is_valid_profile_name(self, name: str) -> bool:
        return ProfileManager.PROFILE_NAME_REGEX.match(name) is not None
