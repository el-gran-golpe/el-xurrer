import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError


DEFAULT_MODEL_CACHE_DIR = Path(".cache/model_router")
DEFAULT_CATALOG_TTL = timedelta(hours=24)


class CachedCatalog(BaseModel):
    fetched_at: datetime
    models: list[dict[str, Any]]


class CachedModelState(BaseModel):
    supports_json_format: bool | None = None
    exhausted_until_datetime: datetime | None = None


class CachedKeyState(BaseModel):
    updated_at: datetime
    models: dict[str, CachedModelState] = Field(default_factory=dict)


class CachedModelCapabilities(BaseModel):
    supports_json_format: bool | None = None


class CachedModelCapabilitiesState(BaseModel):
    updated_at: datetime
    models: dict[str, CachedModelCapabilities] = Field(default_factory=dict)


class ModelCache:
    """On-disk cache for model catalogs and per-key/per-model learned state.

    Every entry is namespaced by provider_id so multiple providers (e.g.
    openrouter, deepseek) can share one cache_dir without colliding.
    """

    def __init__(
        self,
        cache_dir: Path = DEFAULT_MODEL_CACHE_DIR,
        catalog_ttl: timedelta = DEFAULT_CATALOG_TTL,
        now: Callable[[], datetime] | None = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.catalog_ttl = catalog_ttl
        self._now = now or (lambda: datetime.now(timezone.utc))

    def catalog_path(self, provider_id: str) -> Path:
        return self.cache_dir / f"{provider_id}_catalog.json"

    def model_capabilities_path(self, provider_id: str) -> Path:
        return self.cache_dir / f"{provider_id}_capabilities.json"

    def now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def save_catalog(
        self,
        provider_id: str,
        models: list[dict[str, Any]],
        fetched_at: datetime | None = None,
    ) -> None:
        catalog = CachedCatalog(
            fetched_at=self._normalize_datetime(fetched_at or self.now()),
            models=models,
        )
        self._write_json(
            self.catalog_path(provider_id), catalog.model_dump(mode="json")
        )

    def load_catalog(self, provider_id: str) -> CachedCatalog | None:
        payload = self._read_json(self.catalog_path(provider_id))
        if payload is None:
            return None
        try:
            return CachedCatalog.model_validate(payload)
        except ValidationError as e:
            logger.warning(
                "Ignoring invalid {} models catalog cache: {}", provider_id, e
            )
            return None

    def get_catalog(
        self,
        provider_id: str,
        fetch_catalog: Callable[[], list[dict[str, Any]]],
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        cached = self.load_catalog(provider_id)
        if cached is not None and not force_refresh and self._catalog_is_fresh(cached):
            logger.debug(
                "Using cached {} models catalog from {}", provider_id, cached.fetched_at
            )
            return cached.models

        models = fetch_catalog()
        self.save_catalog(provider_id, models)
        return models

    def get_model_state(
        self, provider_id: str, api_key: str, model_id: str
    ) -> CachedModelState | None:
        key_model_state = self._load_key_state(provider_id, api_key).models.get(
            model_id
        )
        capabilities_state = self._load_model_capabilities_state(provider_id)
        model_capabilities = (
            capabilities_state.models.get(model_id)
            if self._capabilities_are_fresh(capabilities_state)
            else None
        )

        if key_model_state is None and model_capabilities is None:
            return None

        return CachedModelState(
            supports_json_format=(
                model_capabilities.supports_json_format
                if model_capabilities is not None
                else None
            ),
            exhausted_until_datetime=(
                key_model_state.exhausted_until_datetime
                if key_model_state is not None
                else None
            ),
        )

    def set_model_exhausted_until(
        self,
        provider_id: str,
        api_key: str,
        model_id: str,
        exhausted_until_datetime: datetime | None,
    ) -> None:
        state = self._load_key_state(provider_id, api_key)
        model_state = state.models.get(model_id, CachedModelState())
        model_state.exhausted_until_datetime = (
            self._normalize_datetime(exhausted_until_datetime)
            if exhausted_until_datetime is not None
            else None
        )
        state.models[model_id] = model_state
        self._save_key_state(provider_id, api_key, state)

    def set_model_json_support(
        self,
        provider_id: str,
        api_key: str,
        model_id: str,
        supports_json_format: bool,
    ) -> None:
        state = self._load_model_capabilities_state(provider_id)
        model_state = state.models.get(model_id, CachedModelCapabilities())
        model_state.supports_json_format = supports_json_format
        state.models[model_id] = model_state
        self._save_model_capabilities_state(provider_id, state)

    def _catalog_is_fresh(self, catalog: CachedCatalog) -> bool:
        fetched_at = self._normalize_datetime(catalog.fetched_at)
        return self.now() - fetched_at < self.catalog_ttl

    def _capabilities_are_fresh(self, state: CachedModelCapabilitiesState) -> bool:
        updated_at = self._normalize_datetime(state.updated_at)
        return self.now() - updated_at < self.catalog_ttl

    def _load_key_state(self, provider_id: str, api_key: str) -> CachedKeyState:
        path = self._key_state_path(provider_id, api_key)
        payload = self._read_json(path)
        if payload is None:
            return CachedKeyState(updated_at=self.now())
        try:
            return CachedKeyState.model_validate(payload)
        except ValidationError as e:
            logger.warning(
                "Ignoring invalid {} model state cache {}: {}", provider_id, path, e
            )
            return CachedKeyState(updated_at=self.now())

    def _save_key_state(
        self, provider_id: str, api_key: str, state: CachedKeyState
    ) -> None:
        state.updated_at = self.now()
        self._write_json(
            self._key_state_path(provider_id, api_key),
            state.model_dump(mode="json"),
        )

    def _load_model_capabilities_state(
        self, provider_id: str
    ) -> CachedModelCapabilitiesState:
        payload = self._read_json(self.model_capabilities_path(provider_id))
        if payload is None:
            return CachedModelCapabilitiesState(updated_at=self.now())
        try:
            return CachedModelCapabilitiesState.model_validate(payload)
        except ValidationError as e:
            logger.warning(
                "Ignoring invalid {} model capabilities cache: {}", provider_id, e
            )
            return CachedModelCapabilitiesState(updated_at=self.now())

    def _save_model_capabilities_state(
        self, provider_id: str, state: CachedModelCapabilitiesState
    ) -> None:
        state.updated_at = self.now()
        self._write_json(
            self.model_capabilities_path(provider_id),
            state.model_dump(mode="json"),
        )

    def _key_state_path(self, provider_id: str, api_key: str) -> Path:
        fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{provider_id}_state_{fingerprint}.json"

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Ignoring unreadable model router cache {}: {}", path, e)
            return None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
