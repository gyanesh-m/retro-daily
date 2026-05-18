# Retro Daily troubleshooting

For installation, see the [top-level README](../README.md). For
what's happening under the hood — workers, state files, sandbox —
see [internals.md](internals.md).

## Scout shows `queued · last run never` forever

The scout-runner background worker spawned but never wrote results. Diagnose:

```sh
tail ~/.claude/plugins/data/retro-daily-retro-daily/scout.log
```

Look for `WARNING: temp results file was not written`. The usual cause is a third-party `PreToolUse` hook (e.g. Sage) returning `"ask"` against the unattended worker — see [Security model](internals.md#security-model-for-background-workers) in internals.md for how the sandbox + `--setting-sources project` combo handles this. If `RETRO_DAILY_NO_BACKGROUND_WORKERS=1` is set, scout is intentionally skipped.

## "I installed it but I don't see anything"

Most likely: plain stdout went to `additionalContext` (LLM-visible only) on v2.1.x. The fixed `startup.sh` emits `systemMessage` so this should be visible — but if you have a stale plugin cache, force an update:

```sh
/plugin marketplace update retro-daily
```

Also check `/tmp/claude-startup.log` — if the dashboard rendered there but not in the terminal, your plugin version is missing the JSON-envelope fix.

## Worker fails with `sandbox unavailable`

Older macOS or stripped-down Linux containers may not have the sandbox toolchain (`sandbox-exec` / `bubblewrap`). `failIfUnavailable: true` causes the worker to abort rather than silently run unsandboxed. To skip scout + tag-sessions entirely on such systems:

```sh
export RETRO_DAILY_NO_BACKGROUND_WORKERS=1
```
