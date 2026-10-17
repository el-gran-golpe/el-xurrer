"""
Pure rendering for `jobs run`'s end-of-run summary and `jobs status`.

Every function here takes plain rows (dicts, as `JobStore` returns them, or
the small dataclasses below) and returns a string. No sqlite, no filesystem,
no loguru — that keeps this module trivial to unit test, and lets the same
rendered table be reused for the loguru line, the `.md` report file, and
`jobs status`'s terminal output.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any

OUTCOME_PLANNED = "planned now"
OUTCOME_REUSED = "reused"
OUTCOME_FAILED = "failed"
OUTCOME_NOT_REACHED = "not reached"
OUTCOME_FROZEN = "frozen (not re-planned)"

SCHEDULE_PUBLISHED = "published"
SCHEDULE_SKIPPED = "skipped"
SCHEDULE_FAILED = "failed"
SCHEDULE_NOT_REACHED = "not reached"

# How long a row's `error` column is allowed to be, so one runaway traceback
# does not blow up the table.
_ERROR_TRUNCATE_CHARS = 200

_FAILED_EVENT_KINDS = {
    "plan_failed",
    "image_failed",
    "schedule_failed",
    "story_failed",
}


@dataclass
class RunRow:
    """One profile x platform x week touched by a `jobs run` invocation."""

    profile: str
    platform: str
    week: str
    outcome: str = OUTCOME_NOT_REACHED
    story: str = ""
    planning_detail: str = ""
    images: str = ""
    schedule: str = SCHEDULE_NOT_REACHED
    error: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.profile, self.platform, self.week)


@dataclass
class OverviewRow:
    """Current (latest-status) state of one profile x platform x week, for
    `jobs status`'s overview, built from the long-lived `jobs` table rather
    than from one run's events."""

    profile: str
    platform: str
    week: str
    story_status: str = "-"
    plan_status: str = "-"
    images_done: int = 0
    images_total: int = 0
    schedule_status: str = "-"


def _truncate(text: str, limit: int = _ERROR_TRUNCATE_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _planning_detail_text(detail: dict[str, Any]) -> str:
    model = detail.get("model") or "unknown"
    fallback = "yes" if detail.get("used_fallback") else "no"
    return (
        f"attempt {detail.get('attempt')}/{detail.get('max_attempts')}, "
        f"model {model}, fallback: {fallback}, "
        f"pinned: {detail.get('pinned_corrections', 0)}"
    )


_IMAGE_KIND_LABELS = {
    "image_generated": "generated",
    "image_reused": "reused",
    "image_stale_removed": "stale removed",
    "image_failed": "failed",
}


_STORY_KIND_LABELS = {
    "arc_done": "arc generated",
    "arc_reused": "arc reused",
    "chapter_done": "chapter generated",
    "chapter_reused": "chapter reused",
}


def _append_story(existing: str, text: str) -> str:
    return f"{existing}, {text}" if existing else text


def build_run_rows(events: list[dict[str, Any]]) -> list[RunRow]:
    """
    One row per profile+platform+week touched by the run, from this run's
    `job_events` rows (`JobStore.events_for_run`), processed in the order
    they were recorded.

    A `story` event has no platform (an arc/chapter covers a whole
    profile+week, not one platform): it lands on its own pseudo-row with
    `platform=""`, alongside — not merged into — the per-platform `plan`
    rows for the same profile+week.

    A `week_not_enqueued` event (recorded on the week whose plan, or whose
    story generation, failed) carries the *next* week in its detail; that
    next week never got a job of its own this run, so it is synthesized
    here as a "not reached" row rather than being silently absent from the
    report.
    """
    rows: dict[tuple[str, str, str], RunRow] = {}
    image_counts: dict[tuple[str, str, str], Counter] = {}
    not_enqueued: list[tuple[str, str, str]] = []

    def row_for(profile: str, platform: str, week: str) -> RunRow:
        key = (profile, platform, week)
        if key not in rows:
            rows[key] = RunRow(profile=profile, platform=platform, week=week)
        return rows[key]

    for event in events:
        profile, week = event["profile"], event["week"]
        platform = event["platform"] or ""
        kind = event["kind"]
        detail = event.get("detail") or {}
        row = row_for(profile, platform, week)

        if kind == "plan_reused":
            row.outcome = OUTCOME_REUSED
        elif kind == "plan_done":
            row.outcome = OUTCOME_PLANNED
            row.planning_detail = _planning_detail_text(detail)
        elif kind == "plan_failed":
            row.outcome = OUTCOME_FAILED
            row.error = _truncate(str(detail.get("error", "")))
        elif kind == "plan_attempt_invalid":
            continue  # folded into plan_done/plan_failed's own detail
        elif kind == "plan_frozen":
            row.outcome = OUTCOME_FROZEN
        elif kind in ("arc_done", "chapter_done"):
            row.story = _append_story(row.story, _STORY_KIND_LABELS[kind])
            row.outcome = OUTCOME_PLANNED
        elif kind in ("arc_reused", "chapter_reused"):
            row.story = _append_story(row.story, _STORY_KIND_LABELS[kind])
            if row.outcome == OUTCOME_NOT_REACHED:
                row.outcome = OUTCOME_REUSED
        elif kind == "story_failed":
            row.outcome = OUTCOME_FAILED
            row.error = _truncate(str(detail.get("error", "")))
        elif kind == "week_not_enqueued":
            next_week = detail.get("next_week")
            if next_week:
                not_enqueued.append((profile, platform, next_week))
        elif kind in _IMAGE_KIND_LABELS:
            counts = image_counts.setdefault((profile, platform, week), Counter())
            counts[_IMAGE_KIND_LABELS[kind]] += 1
            if kind == "image_failed" and not row.error:
                row.error = _truncate(str(detail.get("error", "")))
        elif kind == "schedule_done":
            row.schedule = SCHEDULE_PUBLISHED
        elif kind == "schedule_skipped":
            row.schedule = SCHEDULE_SKIPPED
        elif kind == "schedule_failed":
            row.schedule = SCHEDULE_FAILED
            if not row.error:
                row.error = _truncate(str(detail.get("error", "")))

    for profile, platform, week in not_enqueued:
        key = (profile, platform, week)
        rows.setdefault(key, RunRow(profile=profile, platform=platform, week=week))

    for key, counts in image_counts.items():
        if key in rows:
            rows[key].images = ", ".join(f"{n} {label}" for label, n in counts.items())

    for row in rows.values():
        if not row.images:
            row.images = "-" if row.outcome == OUTCOME_NOT_REACHED else "none"

    return sorted(rows.values(), key=lambda r: r.key())


def count_failures(rows: list[RunRow]) -> int:
    """Rows with any recorded error — a plan, image, or schedule failure —
    regardless of the row's overall `outcome`. This is what `jobs run`'s
    exit code is based on."""
    return sum(1 for row in rows if row.error)


def _markdown_table(headers: list[str], body: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for line in body:
        lines.append("| " + " | ".join(cell or "-" for cell in line) + " |")
    return "\n".join(lines)


def render_totals(rows: list[RunRow]) -> str:
    counts = Counter(row.outcome for row in rows)
    parts = ", ".join(
        f"{counts.get(outcome, 0)} {outcome}"
        for outcome in (
            OUTCOME_PLANNED,
            OUTCOME_REUSED,
            OUTCOME_FAILED,
            OUTCOME_NOT_REACHED,
        )
    )
    failures = count_failures(rows)
    return f"Totals: {len(rows)} row(s) — {parts}; {failures} row(s) with errors."


def render_table(rows: list[RunRow]) -> str:
    """The end-of-run summary: one markdown table plus a totals line. Used
    verbatim for the loguru line, the `.md` report file, and `jobs status`."""
    if not rows:
        return "No profile/platform/week was touched by this run."
    headers = [
        "Profile",
        "Platform",
        "Week",
        "Outcome",
        "Story",
        "Planning",
        "Images",
        "Schedule",
        "Error",
    ]
    body = [
        [
            row.profile,
            row.platform,
            row.week,
            row.outcome,
            row.story,
            row.planning_detail,
            row.images,
            row.schedule,
            row.error,
        ]
        for row in rows
    ]
    return _markdown_table(headers, body) + "\n\n" + render_totals(rows)


def build_overview_rows(jobs: list[dict[str, Any]]) -> list[OverviewRow]:
    """
    `jobs` is a list of dicts with at least `type`, `profile`, `platform`,
    `week`, `status` — the week is not a column on the `jobs` table itself,
    so the caller (`jobs status`) parses it out of each job id first (see
    `jobs/tasks.py:parse_job_id`) and passes it in already resolved, keeping
    this module free of any job-id format knowledge.

    A `story` job has no platform of its own (it covers a whole
    profile+week); its status is looked up by (profile, week) and applied
    to every platform row sharing that profile+week, rather than creating a
    separate platform-less row.
    """
    rows: dict[tuple[str, str, str], OverviewRow] = {}
    story_status: dict[tuple[str, str], str] = {}

    def row_for(profile: str, platform: str, week: str) -> OverviewRow:
        key = (profile, platform, week)
        if key not in rows:
            rows[key] = OverviewRow(profile=profile, platform=platform, week=week)
        return rows[key]

    for job in jobs:
        # Legacy `schedule:{profile}:{platform}` ids from before schedule had
        # a week dimension carry no week; they say nothing about any week.
        if job["week"] == "unknown":
            continue
        if job["type"] == "story":
            story_status[(job["profile"], job["week"])] = job["status"]
            continue
        row = row_for(job["profile"], job["platform"], job["week"])
        if job["type"] == "plan":
            row.plan_status = job["status"]
        elif job["type"] == "schedule":
            row.schedule_status = job["status"]
        elif job["type"] == "generate_image":
            row.images_total += 1
            if job["status"] == "done":
                row.images_done += 1

    for row in rows.values():
        row.story_status = story_status.get((row.profile, row.week), "-")

    return sorted(rows.values(), key=lambda r: (r.profile, r.platform, r.week))


def render_overview(rows: list[OverviewRow]) -> str:
    if not rows:
        return "No jobs recorded yet."
    headers = ["Profile", "Platform", "Week", "Story", "Plan", "Images", "Schedule"]
    body = [
        [
            row.profile,
            row.platform,
            row.week,
            row.story_status,
            row.plan_status,
            f"{row.images_done}/{row.images_total}",
            row.schedule_status,
        ]
        for row in rows
    ]
    return _markdown_table(headers, body)


def render_runs_list(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "No runs recorded yet."
    headers = ["Run", "Started", "Finished", "Outcome", "Failures"]
    body = [
        [
            run["run_id"],
            run["started_at"],
            run["finished_at"] or "running",
            run["outcome"] or "running",
            str(run["failure_count"]),
        ]
        for run in runs
    ]
    return _markdown_table(headers, body)
