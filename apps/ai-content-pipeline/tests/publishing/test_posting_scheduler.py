import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.publishing.posting_scheduler import (
    PostingScheduler,
    _iter_day_folders,
    _pending_publications,
)


def _profile(name):
    return SimpleNamespace(name=name)


@pytest.mark.asyncio
async def test_upload_processes_profiles_concurrently(monkeypatch):
    profiles = [_profile("a"), _profile("b"), _profile("c")]
    delay = 0.05

    async def fake_upload_profile(self, profile):
        await asyncio.sleep(delay)

    monkeypatch.setattr(PostingScheduler, "_upload_profile", fake_upload_profile)

    scheduler = PostingScheduler(
        template_profiles=profiles,
        platform_name=Platform.META,
        publisher=object,
    )

    start = time.monotonic()
    await scheduler.upload()
    elapsed = time.monotonic() - start

    # Sequential execution would take ~3 * delay; concurrent stays near 1 * delay.
    assert elapsed < delay * len(profiles)


@pytest.mark.asyncio
async def test_upload_isolates_one_profile_failure_from_the_rest(monkeypatch):
    profiles = [_profile("failing"), _profile("ok")]
    processed = []

    async def fake_upload_profile(self, profile):
        if profile.name == "failing":
            raise RuntimeError("boom")
        processed.append(profile.name)

    monkeypatch.setattr(PostingScheduler, "_upload_profile", fake_upload_profile)

    scheduler = PostingScheduler(
        template_profiles=profiles,
        platform_name=Platform.META,
        publisher=object,
    )

    await scheduler.upload()

    assert processed == ["ok"]


def test_pending_publications_skips_past_due():
    now = datetime.now(timezone.utc)
    past = SimpleNamespace(upload_time=now - timedelta(days=1))
    future = SimpleNamespace(upload_time=now + timedelta(hours=1))

    assert _pending_publications([past, future]) == [future]


def _make_week_folder(root: Path, week_name: str, days: int = 1) -> None:
    for day in range(1, days + 1):
        (root / week_name / f"day_{day}").mkdir(parents=True)


def test_iter_day_folders_accepts_both_iso_and_legacy_week_names(tmp_path: Path):
    _make_week_folder(tmp_path, "week_1")
    _make_week_folder(tmp_path, "2026-10-12")

    folders = list(_iter_day_folders(tmp_path))

    assert {f.parent.name for f in folders} == {"week_1", "2026-10-12"}


def test_iter_day_folders_rejects_an_invalid_week_name(tmp_path: Path):
    (tmp_path / "not_a_week").mkdir()

    with pytest.raises(ValueError, match="Invalid week folder name"):
        list(_iter_day_folders(tmp_path))


def test_iter_day_folders_with_weeks_only_yields_those_weeks(tmp_path: Path):
    _make_week_folder(tmp_path, "week_1")
    _make_week_folder(tmp_path, "2026-10-12")
    _make_week_folder(tmp_path, "2026-10-19")

    folders = list(_iter_day_folders(tmp_path, weeks={"2026-10-12"}))

    assert {f.parent.name for f in folders} == {"2026-10-12"}


@pytest.mark.asyncio
async def test_upload_profile_only_reads_the_requested_weeks(monkeypatch, tmp_path):
    outputs = tmp_path / "outputs"
    pub_root = outputs / "publications"
    for week_name in ("week_1", "2026-10-12"):
        day = pub_root / week_name / "day_1"
        day.mkdir(parents=True)
        (day / "captions.txt").write_text("hi", encoding="utf-8")
        (day / "upload_times.txt").write_text("2099-01-01T00:00:00Z", encoding="utf-8")
        (day / "pic.jpeg").write_bytes(b"jpeg")

    profile = SimpleNamespace(
        name="haru",
        platform_info={Platform.META: SimpleNamespace(outputs_path=outputs)},
    )

    seen_day_folders: list[Path] = []

    async def fake_upload_via_api(self, publications, client_class, profile):
        seen_day_folders.extend(p.day_folder for p in publications)

    monkeypatch.setattr(PostingScheduler, "_upload_via_api", fake_upload_via_api)

    scheduler = PostingScheduler(
        template_profiles=[profile],
        platform_name=Platform.META,
        publisher=object,
        weeks={"2026-10-12"},
    )
    await scheduler._upload_profile(profile)

    assert [f.parent.name for f in seen_day_folders] == ["2026-10-12"]
