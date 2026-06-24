# warp-degoogled

A private, telemetry-free vendoring of the open-source [Warp](https://github.com/warpdotdev/warp)
terminal (AGPLv3 app + MIT UI crates).

This is **not** a GitHub fork. It is a standalone private repo we fully control, kept
in sync with upstream by automation that re-strips Warp's telemetry / crash-reporting /
cloud-control on every update.

## What is changed vs. upstream

Everything is driven by [`scripts/strip_telemetry.py`](scripts/strip_telemetry.py):

| Area | Upstream | Here |
| --- | --- | --- |
| Usage telemetry (RudderStack) | enqueued + flushed every 30s | `record_*` enqueue fns are no-ops; queue always empty |
| Crash reporting (Sentry) | `init_sentry` + minidump server init | both no-op'd; Sentry never initializes |
| Privacy defaults | telemetry/crash/cloud-storage default `true` | default `false` |

The script is **idempotent** and **fails loudly** if an upstream refactor moves one of
its anchors — so we never silently re-enable telemetry.

> Note: Warp's AI/agent features run on Warp's closed servers and require login; only the
> terminal itself runs locally. De-googling removes phone-home telemetry, not the need to
> log in for cloud features.

## Automation

- **`.github/workflows/sync-upstream.yml`** — daily: pull upstream → overlay → strip → commit.
  Opens an issue if the strip fails.
- **`.github/workflows/build-windows.yml`** — manual only: builds `warp-oss.exe` and uploads
  it as an artifact. No automatic builds.

## Licensing

Upstream is AGPLv3 (app) + MIT (`warpui`/`warpui_core`). Personal use is fine. If you
distribute modified binaries, AGPL requires you to publish the corresponding source.

`vendor-upstream.sha` records which upstream commit the current tree is based on.
