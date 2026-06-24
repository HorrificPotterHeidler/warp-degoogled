#!/usr/bin/env python3
"""Idempotent telemetry / crash-reporting / cloud-control stripper for the Warp client.

Run from the repo root (or anywhere):  python scripts/strip_telemetry.py

Design goals:
  * Idempotent  - running it twice produces no further changes.
  * Loud on drift - if an expected code anchor is missing (upstream refactored the
    telemetry code), the script EXITS NON-ZERO. The daily sync workflow treats that
    as a failure and alerts, so we never silently ship telemetry back in.

What it disables:
  1. Usage telemetry  (RudderStack)  - the record_* enqueue functions become no-ops.
  2. Crash reporting   (Sentry)       - init_sentry + the minidump server's sentry::init.
  3. Privacy defaults                 - telemetry / crash / cloud-conversation default to false.

This is the single source of truth for the de-googling. Manual edits should not be
needed; if upstream changes break an anchor, update THIS script.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARK = "[degoogled]"

errors: list[str] = []
changed: set[str] = set()


def read(rel: str) -> str | None:
    p = ROOT / rel
    if not p.exists():
        errors.append(f"MISSING FILE: {rel}  (upstream may have moved/renamed it)")
        return None
    return p.read_text(encoding="utf-8")


def write(rel: str, old: str, new: str) -> None:
    if new != old:
        (ROOT / rel).write_text(new, encoding="utf-8")
        changed.add(rel)


def replace_fn_body(src: str, rel: str, sig_regex: str, label: str, new_body: str) -> str:
    """Replace a FREE (column-0) function's body with `new_body`.

    `sig_regex` must match the signature up to and including the opening brace `{`.
    The body is taken as everything until the first column-0 `}` (the fn's own close).
    This is a fixed point: re-running yields no change, so it is naturally idempotent.
    """
    pat = re.compile(r"(?P<sig>" + sig_regex + r")\n.*?\n\}", re.DOTALL)
    m = pat.search(src)
    if not m:
        errors.append(f"{rel}: anchor not found for [{label}] (upstream signature changed?)")
        return src
    replacement = m.group("sig") + "\n" + new_body + "\n}"
    return src[: m.start()] + replacement + src[m.end():]


def force_literal(src: str, rel: str, anchor_regex: str, label: str, desired: str) -> str:
    """Force a captured literal (group 'v') to `desired`.

    `anchor_regex` must contain a named group (?P<v>true|false|...) and enough
    structural context (e.g. the setting's struct name) that a genuine upstream
    rename makes the match fail (-> drift alert) rather than silently no-op.
    """
    pat = re.compile(anchor_regex)
    m = pat.search(src)
    if not m:
        errors.append(f"{rel}: anchor not found for [{label}] (upstream structure changed?)")
        return src
    if m.group("v") == desired:
        return src  # already applied
    return src[: m.start("v")] + desired + src[m.end("v"):]


# ---------------------------------------------------------------------------
# 1. Usage telemetry  ->  no-op the enqueue / flush entry points.
#    crates/warpui_core/src/telemetry/mod.rs
# ---------------------------------------------------------------------------
REL = "crates/warpui_core/src/telemetry/mod.rs"
src = read(REL)
if src is not None:
    orig = src
    src = replace_fn_body(
        src, REL,
        r"pub fn record_event\(.*?\)\s*\{",
        "record_event",
        "    // " + MARK + " telemetry disabled: never enqueue any event.\n"
        "    let _ = (user_id, anonymous_id, name, payload, contains_ugc, timestamp);",
    )
    src = replace_fn_body(
        src, REL,
        r"pub fn record_identify_user_event\(.*?\)\s*\{",
        "record_identify_user_event",
        "    // " + MARK + " telemetry disabled: never enqueue any event.\n"
        "    let _ = (user_id, anonymous_id, timestamp);",
    )
    src = replace_fn_body(
        src, REL,
        r"pub fn record_app_active_event\(.*?\)\s*\{",
        "record_app_active_event",
        "    // " + MARK + " telemetry disabled: never enqueue any event.\n"
        "    let _ = (user_id, anonymous_id, timestamp);",
    )
    src = replace_fn_body(
        src, REL,
        r"pub fn flush_events\(\)\s*->\s*Vec<Event>\s*\{",
        "flush_events",
        "    // " + MARK + " telemetry disabled: the queue is always empty.\n"
        "    Vec::new()",
    )
    write(REL, orig, src)

# ---------------------------------------------------------------------------
# 2. Crash reporting (Sentry) -> never initialize.
#    app/src/crash_reporting/mod.rs : init_sentry becomes a no-op body.
# ---------------------------------------------------------------------------
REL = "app/src/crash_reporting/mod.rs"
src = read(REL)
if src is not None:
    orig = src
    src = replace_fn_body(
        src, REL,
        r"fn init_sentry\(.*?\)\s*\{",
        "init_sentry",
        "    // " + MARK + " crash reporting disabled: Sentry is never initialized, so no\n"
        "    // crash or minidump data is ever uploaded.\n"
        "    let _ = (user_id, email, ctx);\n"
        '    log::info!("' + MARK + ' Crash reporting (Sentry) disabled in this build.");',
    )
    write(REL, orig, src)

# ---------------------------------------------------------------------------
# 2b. Crash reporting: the minidump server process also calls sentry::init.
#     app/src/crash_reporting/sentry_minidump.rs
# ---------------------------------------------------------------------------
REL = "app/src/crash_reporting/sentry_minidump.rs"
src = read(REL)
if src is not None:
    orig = src
    if MARK in src and "sentry::init" not in re.sub(r"//.*", "", src):
        pass  # already stripped (init only appears in a comment)
    pat = re.compile(r"^(?P<indent>[ \t]*)let _guard = sentry::init\(super::sentry_client_options\(\)\);",
                     re.MULTILINE)
    m = pat.search(src)
    if m:
        repl = (m.group("indent") + "// " + MARK + " crash reporting disabled: do not init Sentry in\n"
                + m.group("indent") + "// the minidump server process either.\n"
                + m.group("indent") + "// let _guard = sentry::init(super::sentry_client_options());")
        src = src[: m.start()] + repl + src[m.end():]
        write(REL, orig, src)
    elif MARK not in src:
        errors.append(f"{REL}: anchor not found for [minidump sentry::init] (upstream changed?)")

# ---------------------------------------------------------------------------
# 3. Privacy defaults -> false  (defense in depth; also reflects "off" in the UI).
#    app/src/settings/privacy.rs
# ---------------------------------------------------------------------------
REL = "app/src/settings/privacy.rs"
src = read(REL)
if src is not None:
    orig = src
    for field, struct in (
        ("is_telemetry_enabled", "IsTelemetryEnabled"),
        ("is_crash_reporting_enabled", "IsCrashReportingEnabled"),
        ("is_cloud_conversation_storage_enabled", "IsCloudConversationStorageEnabled"),
    ):
        src = force_literal(
            src, REL,
            rf"{field}: {struct} \{{\s*type: bool,\s*default: (?P<v>true|false),",
            f"default {field}",
            "false",
        )
    # refresh_to_default(): force the three booleans to false as well.
    for field in ("is_telemetry_enabled", "is_crash_reporting_enabled",
                  "is_cloud_conversation_storage_enabled"):
        src = force_literal(
            src, REL,
            rf"self\.{field} = (?P<v>true|false);",
            f"refresh_to_default {field}",
            "false",
        )
    write(REL, orig, src)


# ---------------------------------------------------------------------------
print("=== strip_telemetry.py ===")
if changed:
    print("Modified files:")
    for c in sorted(changed):
        print(f"  ~ {c}")
else:
    print("No changes (already stripped / nothing to do).")

if errors:
    print("\nERROR: one or more anchors were not found - upstream telemetry code may")
    print("have changed. Refusing to proceed; a human must review and update this script:")
    for e in errors:
        print(f"  !! {e}")
    sys.exit(1)

print("OK: telemetry / crash reporting / cloud-control defaults stripped.")
