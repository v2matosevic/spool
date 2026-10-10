# Queue cleanup API


All mutations keep the existing local token/bearer and Origin checks. Removal hides history records; no media or partial files are deleted. Removed records survive restart and can be restored by ID. There is no new confirmation requirement for reversible history removal.

| Request | Effect / response |
| --- | --- |
| `POST /api/jobs/{id}/remove` with `{}` | Removes completed/failed/cancelled/interrupted entry. Returns `{removed_ids:[id], count:1, files_deleted:false}`. Already removed is idempotent, count 0. |
| `POST /api/jobs/clear` with `{}` | Removes failed/cancelled/interrupted entries, preserving completed and active jobs. Same removal response with all affected IDs. |
| `POST /api/jobs/clear` with `{"statuses":["completed"]}` | Explicit completed-history cleanup. Other terminal-state combinations are accepted. Active states reject the entire request. |
| `POST /api/jobs/restore` with `{"ids":[...]}` | Undo a removal or bulk clear. Returns `{restored_ids:[...], count:N}`; no downloads restarted. Validates the whole group before writing. |
| `POST /api/jobs/{id}/restore` with `{}` | Single-entry Undo. |
| `POST /api/jobs/retry-failed` with `{}` | Retries failed/interrupted entries within queue capacity, oldest first. Returns `{jobs:[...], skipped:N}`. Explicitly cancelled entries are not automatically retried. |
| Existing `POST /api/jobs/{id}/retry` | Accepts failed/cancelled/interrupted visible entries. Preserves folder/partials but resets old progress/error/warning/stage/ETA. Removed entries must be restored first. |

An active job, including a queued/cancelling job, cannot be removed. Cancel first and wait for a terminal state. Bulk cleanup skips active jobs. Cancelled queued tickets cannot make a later Retry jump ahead of other queued work; each attempt has a separate queue ticket.

`queued_at` records when the current attempt entered the queue. Retry updates it while preserving `created`. Queue-position displays should use `queued_at` (fall back to `created` for legacy records), not the original history creation date.

`GET /api/state` now includes `counts`:

```json
{"active":0,"attention":1,"completed":3,"visible":4,"removed":2,"by_status":{"cancelled":1,"completed":3}}
```

Counts cover all records, while `jobs` keeps the latest 500 visible records. Filtering occurs before the display limit, so removed records cannot hide older visible entries. A specific ID can still be inspected through the existing job endpoint; `removed_at` indicates its archive state.

CLI additions: `remove ID`, `restore ID [ID ...]`, `clear` (attention states), `clear --status completed`, `retry-failed`.

MCP additions: `remove_download`, `clear_download_history`, `restore_downloads`, `retry_failed_downloads`. Existing tool names/arguments remain compatible.

## Batch destinations and completed-file export (1.5)

`POST /api/jobs` accepts optional `folder` (absolute local path for this request) and `flat` (boolean, default false). Flat jobs save directly in the destination; normal jobs keep their ID subfolder. Each new record stores `destination` and `flat`; old records retain the normal-folder behavior. Active deduplication includes source, engine options, destination and layout. Retry preserves layout/path/filename ownership. Flat names include `[spool-JOB_ID]`, with bounded title/source-ID fields so engine truncation cannot remove that suffix. Completion scans only that job's outputs, never every file in the shared directory.

Authenticated `POST /api/jobs/{id}/file-paths` with `{"indexes":[0]}` returns `{"file_paths":["absolute existing path"]}`. Omitted indexes returns all recorded files. It rejects active, removed or missing files, invalid indexes, path traversal and symlinks. The native bridge passes job IDs/indexes through this validation before creating Windows FileDrop and UnicodeText drag data; only Copy is permitted. Copy path uses the same route. Browser file downloads use the same path validation. Nothing moves or deletes existing media.
