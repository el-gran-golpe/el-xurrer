from ai_content_pipeline.jobs import report


def _event(
    profile="haru",
    platform="meta",
    week="2026-09-01",
    kind="plan_done",
    detail=None,
    job_id="plan:haru:meta:2026-09-01",
):
    return {
        "job_id": job_id,
        "type": "plan",
        "profile": profile,
        "platform": platform,
        "week": week,
        "kind": kind,
        "detail": detail,
        "created_at": "2026-09-01T00:00:00+00:00",
    }


def test_build_run_rows_reused_plan():
    rows = report.build_run_rows([_event(kind="plan_reused")])

    assert len(rows) == 1
    assert rows[0].outcome == report.OUTCOME_REUSED
    assert rows[0].error == ""


def test_build_run_rows_planned_now_includes_planning_detail():
    events = [
        _event(
            kind="plan_done",
            detail={
                "attempt": 2,
                "max_attempts": 5,
                "model": "deepseek/chat",
                "used_fallback": True,
                "pinned_corrections": 3,
            },
        )
    ]

    rows = report.build_run_rows(events)

    assert rows[0].outcome == report.OUTCOME_PLANNED
    assert "attempt 2/5" in rows[0].planning_detail
    assert "model deepseek/chat" in rows[0].planning_detail
    assert "fallback: yes" in rows[0].planning_detail
    assert "pinned: 3" in rows[0].planning_detail


def test_build_run_rows_failed_plan_sets_error_and_truncates_it():
    long_error = "x" * 500
    events = [_event(kind="plan_failed", detail={"error": long_error})]

    rows = report.build_run_rows(events)

    assert rows[0].outcome == report.OUTCOME_FAILED
    assert len(rows[0].error) <= 200
    assert rows[0].error.endswith("…")


def test_build_run_rows_image_counts_are_summarized():
    events = [
        _event(kind="plan_done", detail={"attempt": 1, "max_attempts": 5}),
        _event(kind="image_generated", job_id="img:1"),
        _event(kind="image_generated", job_id="img:2"),
        _event(kind="image_reused", job_id="img:3"),
    ]

    rows = report.build_run_rows(events)

    assert "2 generated" in rows[0].images
    assert "1 reused" in rows[0].images


def test_build_run_rows_image_failure_also_sets_the_rows_error():
    events = [
        _event(kind="plan_done", detail={"attempt": 1, "max_attempts": 5}),
        _event(kind="image_failed", job_id="img:1", detail={"error": "comfy exploded"}),
    ]

    rows = report.build_run_rows(events)

    assert rows[0].error == "comfy exploded"


def test_build_run_rows_schedule_outcomes():
    for kind, expected in (
        ("schedule_done", report.SCHEDULE_PUBLISHED),
        ("schedule_skipped", report.SCHEDULE_SKIPPED),
        ("schedule_failed", report.SCHEDULE_FAILED),
    ):
        events = [
            _event(kind="plan_done", detail={"attempt": 1, "max_attempts": 5}),
            _event(
                kind=kind, detail={"error": "boom"} if kind.endswith("failed") else None
            ),
        ]
        rows = report.build_run_rows(events)
        assert rows[0].schedule == expected


def test_build_run_rows_synthesizes_a_not_reached_row_for_the_next_week():
    events = [
        _event(
            week="2026-09-01",
            kind="plan_failed",
            detail={"error": "boom"},
        ),
        _event(
            week="2026-09-01",
            kind="week_not_enqueued",
            detail={"next_week": "2026-09-08"},
        ),
    ]

    rows = report.build_run_rows(events)

    assert len(rows) == 2
    not_reached = next(r for r in rows if r.week == "2026-09-08")
    assert not_reached.outcome == report.OUTCOME_NOT_REACHED


def test_build_run_rows_is_grouped_and_sorted_per_profile_platform_week():
    events = [
        _event(profile="z", week="2026-09-01", kind="plan_reused"),
        _event(profile="a", week="2026-09-08", kind="plan_reused"),
        _event(profile="a", week="2026-09-01", kind="plan_reused"),
    ]

    rows = report.build_run_rows(events)

    assert [r.key() for r in rows] == [
        ("a", "meta", "2026-09-01"),
        ("a", "meta", "2026-09-08"),
        ("z", "meta", "2026-09-01"),
    ]


def test_count_failures_counts_rows_with_any_error():
    rows = report.build_run_rows(
        [
            _event(
                profile="a", kind="plan_done", detail={"attempt": 1, "max_attempts": 5}
            ),
            _event(profile="b", kind="plan_failed", detail={"error": "boom"}),
        ]
    )

    assert report.count_failures(rows) == 1


def test_render_table_for_a_mixed_run_includes_every_outcome_and_totals():
    events = [
        _event(
            profile="planned",
            kind="plan_done",
            detail={"attempt": 1, "max_attempts": 5},
        ),
        _event(profile="reused", kind="plan_reused"),
        _event(profile="failed", kind="plan_failed", detail={"error": "boom"}),
        _event(
            profile="chain",
            week="2026-09-01",
            kind="plan_failed",
            detail={"error": "x"},
        ),
        _event(
            profile="chain",
            week="2026-09-01",
            kind="week_not_enqueued",
            detail={"next_week": "2026-09-08"},
        ),
    ]

    table = report.render_table(report.build_run_rows(events))

    assert "planned" in table
    assert "reused" in table
    assert "failed" in table
    assert "2026-09-08" in table
    assert "Totals:" in table
    assert "row(s) with errors" in table


def test_render_table_with_no_rows():
    assert (
        report.render_table([]) == "No profile/platform/week was touched by this run."
    )


def test_build_overview_rows_combines_plan_images_and_schedule():
    jobs = [
        {
            "profile": "a",
            "platform": "meta",
            "week": "2026-09-01",
            "type": "plan",
            "status": "done",
        },
        {
            "profile": "a",
            "platform": "meta",
            "week": "2026-09-01",
            "type": "generate_image",
            "status": "done",
        },
        {
            "profile": "a",
            "platform": "meta",
            "week": "2026-09-01",
            "type": "generate_image",
            "status": "pending",
        },
        {
            "profile": "a",
            "platform": "meta",
            "week": "2026-09-01",
            "type": "schedule",
            "status": "pending",
        },
    ]

    rows = report.build_overview_rows(jobs)

    assert len(rows) == 1
    row = rows[0]
    assert row.plan_status == "done"
    assert row.images_done == 1
    assert row.images_total == 2
    assert row.schedule_status == "pending"


def test_render_overview_with_no_rows():
    assert report.render_overview([]) == "No jobs recorded yet."


def test_render_runs_list_includes_failure_counts():
    runs = [
        {
            "run_id": "abc123",
            "started_at": "2026-09-01T00:00:00+00:00",
            "finished_at": "2026-09-01T00:05:00+00:00",
            "outcome": "failed",
            "failure_count": 2,
        }
    ]

    table = report.render_runs_list(runs)

    assert "abc123" in table
    assert "failed" in table
    assert "2" in table


def test_render_runs_list_with_no_runs():
    assert report.render_runs_list([]) == "No runs recorded yet."


# ---------------- story events + frozen weeks ----------------


def test_build_run_rows_story_events_land_on_their_own_pseudo_row():
    events = [
        _event(platform=None, kind="arc_reused", job_id="story:haru:2026-09-01"),
        _event(platform=None, kind="chapter_done", job_id="story:haru:2026-09-01"),
        _event(kind="plan_done", detail={"attempt": 1, "max_attempts": 5}),
    ]

    rows = report.build_run_rows(events)

    story_row = next(r for r in rows if r.platform == "")
    assert "arc reused" in story_row.story
    assert "chapter generated" in story_row.story
    # A `chapter_done` after an `arc_reused` is still "planned now" overall.
    assert story_row.outcome == report.OUTCOME_PLANNED
    plan_row = next(r for r in rows if r.platform == "meta")
    assert plan_row.story == ""


def test_build_run_rows_story_failed_sets_outcome_and_error():
    events = [
        _event(platform=None, kind="story_failed", detail={"error": "boom"}),
    ]

    rows = report.build_run_rows(events)

    assert rows[0].outcome == report.OUTCOME_FAILED
    assert rows[0].error == "boom"


def test_build_run_rows_plan_frozen_sets_the_frozen_outcome():
    events = [_event(kind="plan_frozen")]

    rows = report.build_run_rows(events)

    assert rows[0].outcome == report.OUTCOME_FROZEN


def test_render_table_includes_the_story_column_header():
    table = report.render_table(report.build_run_rows([_event(kind="plan_reused")]))

    assert "Story" in table


# ---------------- overview: story status ----------------


def test_build_overview_rows_attaches_story_status_to_every_platform_row():
    jobs = [
        {
            "profile": "a",
            "platform": None,
            "week": "2026-09-01",
            "type": "story",
            "status": "done",
        },
        {
            "profile": "a",
            "platform": "meta",
            "week": "2026-09-01",
            "type": "plan",
            "status": "done",
        },
        {
            "profile": "a",
            "platform": "fanvue",
            "week": "2026-09-01",
            "type": "plan",
            "status": "pending",
        },
    ]

    rows = report.build_overview_rows(jobs)

    assert {r.platform: r.story_status for r in rows} == {
        "meta": "done",
        "fanvue": "done",
    }


def test_build_overview_rows_story_status_defaults_to_dash_without_a_story_job():
    jobs = [
        {
            "profile": "a",
            "platform": "meta",
            "week": "2026-09-01",
            "type": "plan",
            "status": "done",
        },
    ]

    rows = report.build_overview_rows(jobs)

    assert rows[0].story_status == "-"


def test_render_overview_includes_the_story_column_header():
    rows = report.build_overview_rows(
        [
            {
                "profile": "a",
                "platform": "meta",
                "week": "w",
                "type": "plan",
                "status": "done",
            }
        ]
    )

    table = report.render_overview(rows)

    assert "Story" in table
