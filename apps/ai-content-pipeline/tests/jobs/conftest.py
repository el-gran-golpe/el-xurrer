import pytest

from ai_content_pipeline.jobs.store import JobStore


@pytest.fixture
def store() -> JobStore:
    return JobStore(":memory:")
