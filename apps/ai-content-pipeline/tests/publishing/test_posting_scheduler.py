import asyncio
import time
from types import SimpleNamespace

import pytest

from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.publishing.posting_scheduler import PostingScheduler


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
