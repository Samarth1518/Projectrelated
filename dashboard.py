# dashboard.py
# Dashboard processing logic
# Compatible with Python 3.6.5

import json
import os
import re
import difflib
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBSYSTEM_FILE = os.path.join(BASE_DIR, "subsystems.json")
SIMILARITY_THRESHOLD = 0.90


def normalize_name(name):
    name = os.path.basename(str(name)).strip().lower()
    name = re.sub(r"\s+", "", name)
    return name


def similarity_score(name1, name2):
    return difflib.SequenceMatcher(
        None,
        normalize_name(name1),
        normalize_name(name2)
    ).ratio()


def parse_datetime(value):
    if not value:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S"
    ]

    for date_format in formats:
        try:
            return datetime.strptime(str(value).strip(), date_format)
        except (ValueError, TypeError):
            pass

    return None


def load_subsystems():
    with open(SUBSYSTEM_FILE, "r") as file:
        return json.load(file)


def find_best_match(target_name, json_names):
    target = normalize_name(target_name)

    exact_matches = [
        name for name in json_names
        if normalize_name(name) == target
    ]

    if len(exact_matches) == 1:
        return exact_matches[0], "exact"

    if len(exact_matches) > 1:
        return None, "ambiguous"

    scored_matches = []

    for name in json_names:
        score = similarity_score(target_name, name)
        if score >= SIMILARITY_THRESHOLD:
            scored_matches.append((name, score))

    if not scored_matches:
        return None, "unmatched"

    scored_matches.sort(key=lambda item: item[1], reverse=True)
    highest_score = scored_matches[0][1]

    best_matches = [
        item for item in scored_matches
        if abs(item[1] - highest_score) < 0.000001
    ]

    if len(best_matches) != 1:
        return None, "ambiguous"

    return best_matches[0][0], "similar"


def get_ambiguous_candidates(target_name, json_names):
    target = normalize_name(target_name)

    exact_matches = [
        name for name in json_names
        if normalize_name(name) == target
    ]

    if len(exact_matches) > 1:
        return exact_matches

    scored_matches = []

    for name in json_names:
        score = similarity_score(target_name, name)
        if score >= SIMILARITY_THRESHOLD:
            scored_matches.append((name, score))

    if not scored_matches:
        return []

    highest_score = max(item[1] for item in scored_matches)

    return [
        item[0] for item in scored_matches
        if abs(item[1] - highest_score) < 0.000001
    ]


def filter_executions_by_date(executions, date_filter="overall",
                              start_date=None, end_date=None):
    """
    Return (datetime, execution) pairs in the selected period.
    Date Range boundaries are inclusive.
    """

    start_datetime = None
    end_datetime = None

    if date_filter == "date_range":
        if not start_date or not end_date:
            raise ValueError("Both start date and end date are required.")

        try:
            start_datetime = datetime.strptime(
                str(start_date), "%Y-%m-%d"
            )
            end_datetime = datetime.strptime(
                str(end_date), "%Y-%m-%d"
            ).replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            raise ValueError("Invalid date. Use YYYY-MM-DD.")

        if start_datetime > end_datetime:
            raise ValueError("Start date cannot be later than end date.")

    elif date_filter != "overall":
        raise ValueError("Invalid date filter. Use overall or date_range.")

    filtered = []

    for execution in executions:
        if not isinstance(execution, dict):
            continue

        execution_date = parse_datetime(execution.get("date_time", ""))
        if execution_date is None:
            continue

        if date_filter == "overall":
            filtered.append((execution_date, execution))
        elif start_datetime <= execution_date <= end_datetime:
            filtered.append((execution_date, execution))

    return filtered


def get_latest_execution(procedure_data, date_filter="overall",
                         start_date=None, end_date=None):
    executions = procedure_data.get("procedures", [])

    filtered = filter_executions_by_date(
        executions,
        date_filter,
        start_date,
        end_date
    )

    if not filtered:
        return None

    filtered.sort(key=lambda item: item[0], reverse=True)
    return filtered[0][1]


def get_date_range(json_procedures, date_filter="overall",
                   start_date=None, end_date=None):
    if date_filter == "date_range":
        # Display the user's selected range even when it contains no executions.
        start_value = datetime.strptime(
            str(start_date), "%Y-%m-%d"
        ).strftime("%d-%m-%Y")
        end_value = datetime.strptime(
            str(end_date), "%Y-%m-%d"
        ).strftime("%d-%m-%Y")
        return start_value + " to " + end_value

    all_dates = []

    for procedure_data in json_procedures.values():
        executions = procedure_data.get("procedures", [])
        for execution_date, execution in filter_executions_by_date(
                executions, "overall"):
            all_dates.append(execution_date)

    if not all_dates:
        return "Date range unavailable"

    return (
        min(all_dates).strftime("%d-%m-%Y")
        + " to "
        + max(all_dates).strftime("%d-%m-%Y")
    )


def _classify_status(execution):
    return str(execution.get("final_status", "")).strip().lower()


def process_dashboard(json_path, project_name="", date_filter="overall",
                      start_date=None, end_date=None, subsystems_data=None):
    """
    Overall: latest execution across all dates.
    Date Range: latest execution inside the selected inclusive date range.
    Original generated JSON is read only and is never modified.
    """

    if date_filter not in ("overall", "date_range"):
        raise ValueError("Invalid date filter selected.")

    if date_filter == "date_range":
        if not start_date or not end_date:
            raise ValueError("Please select both start and end dates.")

        start_check = datetime.strptime(str(start_date), "%Y-%m-%d")
        end_check = datetime.strptime(str(end_date), "%Y-%m-%d")

        if start_check > end_check:
            raise ValueError("Start date cannot be later than end date.")

    subsystems = subsystems_data if subsystems_data is not None else load_subsystems()

    with open(json_path, "r") as json_file:
        json_data = json.load(json_file)

    json_procedures = {
        name: data
        for name, data in json_data.items()
        if name != "Insights" and isinstance(data, dict)
    }

    json_names = list(json_procedures.keys())

    date_range = get_date_range(
        json_procedures,
        date_filter,
        start_date,
        end_date
    )

    results = []
    assigned_names = set()
    reserved_names = set()

    for subsystem_name, configured_names in subsystems.items():
        success_names = []
        failure_names = []
        unmatched_names = []
        ambiguous_names = []
        no_execution_names = []

        for configured_name in configured_names:
            matched_name, match_type = find_best_match(
                configured_name,
                json_names
            )

            if matched_name is None:
                if match_type == "ambiguous":
                    ambiguous_names.append(configured_name)
                    candidates = get_ambiguous_candidates(
                        configured_name,
                        json_names
                    )
                    reserved_names.update(candidates)
                else:
                    unmatched_names.append(configured_name)
                continue

            # Preserve the existing first-assignment priority.
            if matched_name in assigned_names:
                ambiguous_names.append(configured_name)
                reserved_names.add(matched_name)
                continue

            assigned_names.add(matched_name)

            latest = get_latest_execution(
                json_procedures[matched_name],
                date_filter,
                start_date,
                end_date
            )

            if latest is None:
                # This is a real matched procedure with no execution in
                # the selected dates. It is not an unmatched filename.
                no_execution_names.append(configured_name)
                continue

            final_status = _classify_status(latest)

            if final_status == "success":
                success_names.append(configured_name)
            elif final_status == "failure":
                failure_names.append(configured_name)
            else:
                unmatched_names.append(configured_name)

        success_count = len(success_names)
        failure_count = len(failure_names)
        total = success_count + failure_count

        results.append({
            "name": subsystem_name,
            "success": success_names,
            "failure": failure_names,
            "unmatched": unmatched_names,
            "ambiguous": ambiguous_names,
            "no_execution": no_execution_names,
            "success_count": success_count,
            "failure_count": failure_count,
            "unmatched_count": len(unmatched_names),
            "ambiguous_count": len(ambiguous_names),
            "no_execution_count": len(no_execution_names),
            "total": total,
            "success_percentage": round(
                success_count * 100.0 / total, 2
            ) if total else 0,
            "failure_percentage": round(
                failure_count * 100.0 / total, 2
            ) if total else 0
        })

    unassigned_success = []
    unassigned_failure = []

    for procedure_name, procedure_data in json_procedures.items():
        if procedure_name in assigned_names:
            continue

        if procedure_name in reserved_names:
            continue

        latest = get_latest_execution(
            procedure_data,
            date_filter,
            start_date,
            end_date
        )

        if latest is None:
            continue

        final_status = _classify_status(latest)

        if final_status == "success":
            unassigned_success.append(procedure_name)
        elif final_status == "failure":
            unassigned_failure.append(procedure_name)

    unassigned_procedures = {
        "success": unassigned_success,
        "failure": unassigned_failure,
        "success_count": len(unassigned_success),
        "failure_count": len(unassigned_failure),
        "total": len(unassigned_success) + len(unassigned_failure)
    }

    return {
        "project_name": project_name,
        "date_range": date_range,
        "date_filter": date_filter,
        "start_date": start_date or "",
        "end_date": end_date or "",
        "subsystems": results,
        "unassigned_procedures": unassigned_procedures
    }
