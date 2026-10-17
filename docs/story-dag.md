# Story → plan flow

What `jobs run` does for one profile and one target week `W`, from the season
arc down to each platform's weekly plan. Diamonds are the conditions that
decide what is reused, generated, regenerated or blocked. The code is the
source of truth (`jobs/tasks.py:run_story`/`run_plan`,
`planning/story_manager.py`, `planning/planning_manager.py`); keep this
diagram in sync when those conditions change.

```mermaid
flowchart TD
  RUN(["jobs run --weeks N"]) --> W["W = target Monday<br/>today if Monday, else next Monday"]
  W --> A1

  subgraph STORY["story · profile, W"]
    A1{"arc covering W<br/>on disk?"}
    A1 -- no --> A2["generate arc<br/>starts after the previous arc"]
    A1 -- yes --> C1
    A2 -- ok --> C1
    C1{"chapter covering W<br/>on disk?"}
    C1 -- no --> C2["generate chapter<br/>outline + 1 call per week"]
    C1 -- yes --> E1{"a day's situation edited<br/>but not its angles?<br/>(week not started)"}
    E1 -- yes --> E2["regenerate those days' angles"]
  end

  A2 -- fails --> SF["story_failed<br/>no plan for W, no story W+1"]
  C2 -- fails --> SF
  E2 -- fails --> SF
  E1 -- no --> OK["arc + chapter ready"]
  E2 -- ok --> OK
  C2 -- ok --> OK

  OK --> NX{"weeks left?"}
  NX -- yes --> NEXT(["story · W+1"])
  OK --> H

  subgraph PLAN["plan · profile, P, W   (once per P = meta, fanvue)"]
    H["fingerprint = prompts + persona + P notes<br/>+ week W of the chapter: situation + P angle"]
    H --> D{"plan done?"}
    D -- yes --> HC{"fingerprint changed?"}
    HC -- no --> R["reuse"]
    HC -- yes --> FZ{"W already started?"}
    FZ -- yes --> FR["frozen: left as is"]
    FZ -- no --> G
    D -- no --> G["ask the model for the plan"]
    G --> V{"valid?<br/>JSON, days 1-7, ≥1 post/day"}
    V -- "no, attempt < 5" --> X["exclude that model<br/>(5th attempt: DeepSeek only)"] --> G
    V -- "no, attempt 5" --> PF["plan_failed"]
    V -- yes --> SV["save plan<br/>previous week → history<br/>remove stale images"]
  end

  R --> IMG(["images → schedule"])
  FR --> IMG
  SV --> IMG
```

## Rules the diagram does not show

- **What is on disk wins.** An existing arc or chapter is never regenerated
  because the persona or notes changed: both are meant to be edited by hand.
  Only `arc plan --force` / `chapter plan --force` rebuild them.
- **Angles follow the situation.** Each chapter day stores a fingerprint of
  its situation and angles. Editing only a situation regenerates that day's
  angles; editing the angles too keeps yours. Days in a week that already
  started are never touched.
- **Retries.** The arc, the chapter outline, each chapter week, each angle
  refresh and each plan get 5 attempts. After an invalid reply that model is
  excluded, and the last attempt goes to the paid fallback (DeepSeek). If any
  chapter call fails, nothing is saved.
- **Isolation.** Platform P's plan only sees the chapter's situation and P's
  own angle, never the arc or the other platform's angle or notes.
- **What triggers a re-plan.** Only a change in that plan's fingerprint:
  prompts, persona, P's notes, or week W of the chapter. Editing another week
  does not touch W.
- **Sizes.** `story/config.json` holds `arc_weeks` (default 12) and
  `chapter_weeks` (default 4). Chapters tile the arc from its start; the last
  one may be shorter.
- **Outside `jobs run`.** `meta plan`, `fanvue plan` and `all run_all` also
  make sure the arc and chapter exist (and reconcile hand edits) before
  planning, without fingerprints or frozen weeks.
