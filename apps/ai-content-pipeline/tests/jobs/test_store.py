from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.jobs.store import JobStatus, JobStore, JobType


def _store() -> JobStore:
    return JobStore(":memory:")


def test_create_seeds_a_new_job_as_pending():
    store = _store()
    status = store.create("plan:haru:meta", JobType.PLAN, "haru", Platform.META)
    assert status is JobStatus.PENDING
    assert store.status("plan:haru:meta") is JobStatus.PENDING


def test_unknown_job_has_no_status():
    store = _store()
    assert store.status("nope") is None


def test_running_then_done_transitions():
    store = _store()
    job_id = "plan:haru:meta"
    store.create(job_id, JobType.PLAN, "haru", Platform.META)

    store.mark_running(job_id)
    assert store.status(job_id) is JobStatus.RUNNING

    store.mark_done(job_id)
    assert store.status(job_id) is JobStatus.DONE


def test_resume_skips_a_done_job_with_matching_params_hash():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )
    store.mark_done(job_id)

    status = store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )

    assert status is JobStatus.DONE


def test_resume_reruns_a_done_job_whose_params_hash_changed():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )
    store.mark_done(job_id)

    status = store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="different"
    )

    assert status is JobStatus.PENDING


def test_resume_reruns_a_previously_failed_job():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(job_id, JobType.GENERATE_IMAGE, "haru", Platform.META)
    store.mark_failed(job_id, "boom")

    status = store.create(job_id, JobType.GENERATE_IMAGE, "haru", Platform.META)

    assert status is JobStatus.PENDING
    assert store.status(job_id) is JobStatus.PENDING


def test_resume_leaves_a_pending_job_untouched():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )

    status = store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="different"
    )

    assert status is JobStatus.PENDING


def test_fan_in_counter_reaches_zero_after_every_decrement():
    store = _store()
    store.init_counter("haru:meta", 3)

    assert store.decrement_counter("haru:meta") == 2
    assert store.decrement_counter("haru:meta") == 1
    assert store.decrement_counter("haru:meta") == 0


def test_init_counter_is_idempotent():
    store = _store()
    store.init_counter("haru:meta", 3)
    store.decrement_counter("haru:meta")
    store.init_counter("haru:meta", 3)  # re-seed on resume must not reset progress

    assert store.decrement_counter("haru:meta") == 1
