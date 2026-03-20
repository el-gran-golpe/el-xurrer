# Global LLM Intelligence Routing Design

## Goal

Route GitHub Models requests to the smartest currently available model across all configured GitHub API keys, while preserving existing capability filters and quota failover.

## Current State

`ModelClassifier` owns the model catalog for one GitHub API key. It probes catalog entries for quota availability, JSON schema support, and rough censorship classification, and stores the results in `LLMModel`.

`ModelRouter` currently rotates across classifiers by API key first, then sorts candidate models by `elo` only within the current key. That means the router does not guarantee selection of the globally strongest available GitHub model. A temporarily exhausted model can recover inside a classifier, but the router may still keep preferring a weaker model from the current key.

The scoreboard integration in `llm/routing/classification/model_classifier.py` is currently unfinished. `LLMModel.elo` stays at its placeholder default unless set manually.

## Requirements

1. Use LMArena leaderboard data to assign an intelligence score to GitHub Models when possible.
2. Pick the highest-scoring eligible model across all GitHub API keys, not per key.
3. Preserve existing prompt capability filters:
   - Skip censored models for sensitive prompts.
   - Skip models without JSON support when JSON output is required.
4. Preserve quota failover:
   - Mark only the rate-limited `(api key, model)` instance as exhausted.
   - Continue with the next-best global candidate.
5. When a cooldown expires, the recovered model must automatically become first choice again if it is globally the smartest eligible model.
6. If leaderboard fetching or parsing fails, routing must still work with a safe fallback.

## Recommended Approach

Keep `ModelClassifier` responsible for one GitHub API key and all per-key state. Add scoreboard ingestion there so the classifier updates each local `LLMModel.elo` during initialization.

Change `ModelRouter` so it no longer chooses a key first. Instead, for each request it asks every classifier for its currently eligible models, flattens those results into a single global candidate pool, sorts the pool by descending intelligence score, and tries candidates in that order.

This is the smallest change that satisfies the routing requirement without collapsing the existing classifier boundary.

## Score Source

Use the latest LMArena leaderboard artifact from the Hugging Face space and fill `LLMModel.elo` from that data during classifier initialization.

Prefer a dated `leaderboard_table_YYYYMMDD.csv` if it is available, because it is simpler and more robust than unpickling leaderboard snapshots. Fall back to the existing pickle strategy only if the CSV path is unavailable. The goal is only to extract a stable per-model rating for ranking, not to reproduce the full leaderboard application.

If the score source cannot be loaded, keep unmatched or unscored models at a low default `elo` and continue startup.

## Model Matching

Use layered matching between GitHub model IDs and leaderboard model names:

1. Exact identifier match.
2. Normalized match after removing punctuation, separators, and case differences.
3. Small alias mapping for known naming mismatches between GitHub Models and LMArena.

If a GitHub model still does not match a leaderboard entry, leave its `elo` at the default low value and log the miss for later alias expansion.

If the same model is available through multiple GitHub API keys, each copy keeps the same intelligence score but retains independent quota state.

## Routing Design

For each request:

1. Each classifier returns its currently eligible models.
2. Eligibility remains local to the classifier:
   - Quota is available or has recovered.
   - JSON support is sufficient for the prompt.
   - Censorship policy is compatible with the prompt.
3. The router combines all eligible models from all classifiers into one list.
4. The router sorts the list by descending `elo`.
5. A stable secondary tie-breaker should keep order deterministic. Token limits or identifier order are sufficient.
6. The router tries candidates in that global order until one succeeds.

This removes key-first bias and guarantees that the globally smartest currently eligible GitHub model is always attempted first.

## Quota Recovery Behavior

Quota exhaustion remains tracked per `LLMModel` instance. When a request receives a `RateLimitError`, the owning classifier marks that specific model exhausted until the cooldown timestamp.

Recovery requires no special router state. On the next request, `ModelClassifier._is_quota_recovered()` will clear exhaustion once the timestamp has passed. Because the router rebuilds the global candidate list on every request, the recovered model immediately re-enters the pool and returns to the top if it still has the best intelligence score.

## Error Handling

Leaderboard loading should happen during initialization, not during request handling.

If leaderboard listing, download, parsing, or matching fails:

- Log the concrete failure stage.
- Leave existing models in the catalog.
- Keep their default `elo` values.
- Continue using capability and quota routing.

This keeps the router resilient if Hugging Face or leaderboard format changes.

## Testing Strategy

Add unit tests for:

1. Score assignment:
   - Matched models get leaderboard-derived `elo`.
   - Unmatched models keep the default score.
2. Global routing:
   - The router picks the highest-`elo` eligible model across all keys.
   - A stronger model on a non-current key beats a weaker model on the previously successful key.
3. Quota failover and recovery:
   - The best model is skipped once exhausted.
   - After cooldown expiry, it becomes first choice again on the next request.
4. Resilience:
   - Leaderboard fetch or parse failure does not break router initialization.

Tests should stay unit-level by mocking leaderboard fetches and model responses instead of calling GitHub Models or Hugging Face.

## Files Expected To Change

- `llm/routing/classification/model_classifier.py`
- `llm/routing/model_router.py`
- `llm/routing/classification/constants.py`
- `tests/...` for new routing and classifier unit tests

## Out Of Scope

- Reworking the broader censorship heuristic.
- Changing DeepSeek fallback behavior beyond preserving current semantics after GitHub candidates are exhausted.
- Building a persistent cache for leaderboard artifacts.
