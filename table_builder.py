# table_builder.py
# Builds a flat, table-style JSON (one row per procedure execution, plus a
# per-procedure summary) from the nested output_data produced by main.py.
# Compatible with Python 3.6.5. No third-party packages needed.

import json
import os
from collections import OrderedDict

STATUS_NAMES = ("success", "failure", "suspend", "progress")

COLUMNS = [
    "procedure_name",
    "run_no",
    "date",
    "time",
    "date_time",
    "duration_sec",
    "mode",
    "final_status",
    "total_steps",
    "success_count",
    "failure_count",
    "suspend_count",
    "progress_count",
    "failed_steps",
    "failure_reason",
    "auto_status",
]

SUMMARY_COLUMNS = [
    "procedure_name",
    "total_executions",
    "success_runs",
    "failure_runs",
    "latest_date",
    "latest_time",
    "latest_date_time",
    "latest_mode",
    "latest_final_status",
    "modes_used",
    "total_duration_sec",
]


def _mode_label(mode_executions):
    """Auto / Manual / Auto + Manual, based on which mode actually ran steps."""
    mode_executions = mode_executions or {}
    auto = mode_executions.get("auto") or {}
    manual = mode_executions.get("manual") or {}

    auto_used = bool(auto.get("date_time_status")) or any(
        auto.get(s) for s in STATUS_NAMES
    )
    manual_used = any(manual.get(s) for s in STATUS_NAMES)

    if auto_used and manual_used:
        return "Auto + Manual"
    if auto_used:
        return "Auto"
    if manual_used:
        return "Manual"
    return "Unknown"


def _split_date_time(value):
    """'2025-12-31 11:44:33.256' -> ('2025-12-31', '11:44:33.256')."""
    value = (value or "").strip()
    if not value:
        return "", ""
    parts = value.split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _failure_info(execution):
    """Return (failed step ids joined, reason text joined)."""
    reasons = execution.get("final_status_reason")
    ids = []
    texts = []

    if isinstance(reasons, list):
        for item in reasons:
            if isinstance(item, dict):
                for step_id, text in item.items():
                    ids.append(step_id)
                    texts.append(step_id + ": " + str(text))

    if not ids:
        ids = list((execution.get("Status") or {}).get("failure", []))

    return ", ".join(ids), " | ".join(texts)


def _auto_status(execution):
    events = (
        ((execution.get("mode_executions") or {}).get("auto") or {})
        .get("date_time_status")
        or []
    )
    if events:
        return events[-1].get("status", "") or ""
    return ""


def build_table(output_data):
    """Return an OrderedDict with 'table' and 'procedure_summary' sections."""
    rows = []

    for procedure_name, group in output_data.items():
        if procedure_name == "Insights":
            continue

        executions = list(group.get("procedures", []))
        executions.sort(key=lambda e: e.get("date_time", "") or "")

        for run_no, execution in enumerate(executions, 1):
            date_text, time_text = _split_date_time(execution.get("date_time"))
            status = execution.get("Status") or {}
            failed_steps, failure_reason = _failure_info(execution)

            row = OrderedDict()
            row["procedure_name"] = procedure_name
            row["run_no"] = run_no
            row["date"] = date_text
            row["time"] = time_text
            row["date_time"] = execution.get("date_time", "")
            row["duration_sec"] = execution.get("Dur", 0)
            row["mode"] = _mode_label(execution.get("mode_executions"))
            row["final_status"] = execution.get("final_status", "")
            row["total_steps"] = sum(len(status.get(s, [])) for s in STATUS_NAMES)
            row["success_count"] = len(status.get("success", []))
            row["failure_count"] = len(status.get("failure", []))
            row["suspend_count"] = len(status.get("suspend", []))
            row["progress_count"] = len(status.get("progress", []))
            row["failed_steps"] = failed_steps
            row["failure_reason"] = failure_reason
            row["auto_status"] = _auto_status(execution)
            rows.append(row)

    rows.sort(key=lambda r: (r["procedure_name"].lower(), r["date_time"]))

    # ---- per-procedure summary ----
    summary = []
    by_proc = OrderedDict()
    for row in rows:
        by_proc.setdefault(row["procedure_name"], []).append(row)

    for name, proc_rows in by_proc.items():
        latest = proc_rows[-1]  # rows already sorted by date_time
        modes_used = sorted(set(r["mode"] for r in proc_rows))

        item = OrderedDict()
        item["procedure_name"] = name
        item["total_executions"] = len(proc_rows)
        item["success_runs"] = sum(1 for r in proc_rows if r["final_status"] == "Success")
        item["failure_runs"] = sum(1 for r in proc_rows if r["final_status"] == "Failure")
        item["latest_date"] = latest["date"]
        item["latest_time"] = latest["time"]
        item["latest_date_time"] = latest["date_time"]
        item["latest_mode"] = latest["mode"]
        item["latest_final_status"] = latest["final_status"]
        item["modes_used"] = ", ".join(modes_used)
        item["total_duration_sec"] = sum(r["duration_sec"] or 0 for r in proc_rows)
        summary.append(item)

    result = OrderedDict()
    result["procedure_summary"] = OrderedDict([
        ("columns", SUMMARY_COLUMNS),
        ("rows", summary),
    ])
    result["table"] = OrderedDict([
        ("columns", COLUMNS),
        ("rows", rows),
    ])
    result["Insights"] = output_data.get("Insights", {})
    return result


def write_table(output_data, path):
    """Write the table JSON safely (temp file, validate, then rename)."""
    table = build_table(output_data)
    temp_path = path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(table, f, indent=4, ensure_ascii=False)
            f.write("\n")
        with open(temp_path, "r", encoding="utf-8") as f:
            json.load(f)
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise

    return path
