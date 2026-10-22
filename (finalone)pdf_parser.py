
# pdf_parser.py
# Extract procedure and STEP information from PDF text.
# Compatible with Python 3.6.5.

import re
from datetime import datetime


STATUS_NAMES = ("success", "failure", "suspend", "progress")

STATUS_TITLE = {
    "success": "Success",
    "failure": "Failure",
    "suspend": "Suspend",
    "progress": "Progress",
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

STEP_ID_RE = re.compile(r"^\s*(\d{2}\.\d{3,4})\b")
MODE_RE = re.compile(r"^\s*MODE\b", re.IGNORECASE)
OPERATING_MODE_RE = re.compile(
    r"^\s*OPERATING\s+MODE\b", re.IGNORECASE
)
MODE_NAME_RE = re.compile(r"\b(AUTO|MANUAL)\b", re.IGNORECASE)

DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})[-/]([A-Za-z]{3}|\d{1,2})[-/](\d{4})(?!\d)",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"(?<!\d)(\d{1,2}):(\d{2}):(\d{2})[:.](\d{1,3})(?!\d)"
)
DATE_TIME_RE = re.compile(
    r"(?<!\d)(\d{1,2})[-/]([A-Za-z]{3}|\d{1,2})[-/](\d{4})"
    r"\s+(\d{1,2}):(\d{2}):(\d{2})[:.](\d{1,3})(?!\d)",
    re.IGNORECASE,
)
DURATION_RE = re.compile(
    r"\bDur\s*:\s*(\d+(?:\.\d+)?)\s*\(s\)", re.IGNORECASE
)
STATUS_WORD_RE = re.compile(
    r"\b(Success|Failure|Suspend|Progress)\b", re.IGNORECASE
)
SEPARATOR_RE = re.compile(r"^[\s\-_=*|]+$")


def normalize_procedure_name(name):
    """Normalize a procedure name for grouping."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def normalize_datetime(value):
    """Convert a supported date/time to YYYY-MM-DD HH:MM:SS.mmm."""
    match = DATE_TIME_RE.search(value or "")
    if not match:
        return None

    day, month_text, year, hour, minute, second, millis = match.groups()

    if month_text.isdigit():
        month = int(month_text)
    else:
        month = MONTHS.get(month_text.lower()[:3])

    if month is None or not 1 <= month <= 12:
        return None

    try:
        parsed = datetime(
            int(year), month, int(day),
            int(hour), int(minute), int(second)
        )
    except ValueError:
        return None

    return (
        parsed.strftime("%Y-%m-%d %H:%M:%S")
        + "."
        + millis[:3].ljust(3, "0")
    )


def _combine_split_date_time(lines):
    """Join dates and times that are split across adjacent lines."""
    combined = []
    index = 0

    while index < len(lines):
        line = lines[index]
        date_match = DATE_RE.search(line)

        if (
            date_match
            and not DATE_TIME_RE.search(line)
            and index + 1 < len(lines)
        ):
            next_line = lines[index + 1]
            time_match = TIME_RE.search(next_line)

            if time_match:
                combined.append(
                    line[:date_match.start()]
                    + date_match.group(0)
                    + " "
                    + time_match.group(0)
                    + next_line[time_match.end():]
                )
                index += 2
                continue

        combined.append(line)
        index += 1

    return combined


def split_procedure_blocks(text):
    """Split the document whenever a new Procedure: header begins."""
    matches = list(
        re.finditer(r"\bProcedure\s*:", text or "", re.IGNORECASE)
    )
    blocks = []

    for index, match in enumerate(matches):
        start = match.start()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        blocks.append(text[start:end])

    return blocks


def extract_metadata(block):
    """Extract procedure name, timestamp, and rounded duration."""
    name_match = re.search(
        r"\bProcedure\s*:\s*(.*?)\s+\bTime\s*:",
        block,
        re.IGNORECASE | re.DOTALL,
    )
    name = ""

    if name_match:
        name = re.sub(r"\s+", " ", name_match.group(1)).strip()

    table_match = re.search(r"\bSTEP\s+ID\b", block, re.IGNORECASE)
    header = block[:table_match.start()] if table_match else block

    date_time = normalize_datetime(header)

    duration_match = DURATION_RE.search(header)
    duration = None

    if duration_match:
        duration = int(float(duration_match.group(1)) + 0.5)

    return name, date_time, duration


def _is_mode_start(line):
    """Recognize a MODE marker."""
    return bool(MODE_RE.match(line or ""))


def _mode_name(lines):
    """Find AUTO or MANUAL in a MODE event."""
    saw_mode = False

    for line in lines:
        if _is_mode_start(line):
            saw_mode = True

        if saw_mode:
            match = MODE_NAME_RE.search(line)
            if match:
                return match.group(1).lower()

    return None


def _status_near_timestamp(lines):
    """Find the status associated with a timestamp."""
    timestamp_seen = False

    for line in lines:
        date_match = DATE_RE.search(line)
        time_match = TIME_RE.search(line)

        if date_match or time_match:
            timestamp_seen = True

            if time_match:
                suffix = line[time_match.end():]
                matches = list(STATUS_WORD_RE.finditer(suffix))

                if matches:
                    return matches[-1].group(1).lower()

            continue

        if timestamp_seen:
            match = re.match(
                r"^(Success|Failure|Suspend|Progress)\b",
                line.strip(),
                re.IGNORECASE,
            )

            if match:
                return match.group(1).lower()

    return None


def _description_and_reason(step_lines, warnings, step_id):
    """Extract STEP description and continuation text."""
    lines = _combine_split_date_time(step_lines)
    description_parts = []
    detail_parts = []
    timestamp_seen = False

    for raw_line in lines:
        line = raw_line.strip()

        if not line or SEPARATOR_RE.fullmatch(line):
            continue

        line = STEP_ID_RE.sub("", line).strip()

        date_match = DATE_RE.search(line)
        time_match = TIME_RE.search(line)
        positions = []

        if date_match:
            positions.append(date_match.start())

        if time_match:
            positions.append(time_match.start())

        if positions:
            boundary = min(positions)
            before_timestamp = line[:boundary].strip()
            after_timestamp = line[boundary:].strip()

            if before_timestamp:
                if timestamp_seen:
                    detail_parts.append(before_timestamp)
                else:
                    description_parts.append(before_timestamp)

            after_timestamp = DATE_TIME_RE.sub(" ", after_timestamp)
            after_timestamp = DATE_RE.sub(" ", after_timestamp)
            after_timestamp = TIME_RE.sub(" ", after_timestamp)
            after_timestamp = re.sub(
                r"\b(Success|Failure|Suspend|Progress)\s*$",
                "",
                after_timestamp,
                flags=re.IGNORECASE,
            ).strip()

            if after_timestamp:
                detail_parts.append(after_timestamp)

            timestamp_seen = True
            continue

        if re.match(
            r"^(Success|Failure|Suspend|Progress)\s*$",
            line,
            re.IGNORECASE,
        ):
            continue

        if timestamp_seen:
            detail_parts.append(line)
        else:
            description_parts.append(line)

    description = re.sub(
        r"\s+", " ", " ".join(description_parts)
    ).strip()
    details = re.sub(
        r"\s+", " ", " ".join(detail_parts)
    ).strip()

    if description and details:
        full_text = description + ", " + details
    else:
        full_text = description or details

    if not full_text:
        warnings.append(
            "STEP " + step_id
            + " has no confidently extracted description."
        )

    return description, details, full_text


def _read_mode_event(mode_lines, warnings):
    """Extract timestamp and status from a MODE event."""
    lines = _combine_split_date_time(mode_lines)
    date_time = normalize_datetime(" ".join(lines))
    status = _status_near_timestamp(lines)

    if not date_time or not status:
        warnings.append(
            "A MODE row has a missing or unrecognized timestamp/status."
        )

    return {
        "date_time": date_time or "",
        "status": STATUS_TITLE.get(status, "") if status else "",
    }


def _new_status_lists():
    return {name: [] for name in STATUS_NAMES}


def _parse_procedure_steps(block, source_name, execution_number):
    """Extract STEP rows and assign each row to its active mode."""
    warnings = []
    overall_status = _new_status_lists()
    mode_status = {
        "auto": _new_status_lists(),
        "manual": _new_status_lists(),
    }
    auto_date_time_status = []
    failure_reasons = []
    seen_ids = set()

    lines = block.splitlines()
    table_started = False
    current_mode = "manual"
    rows = []

    current_step_id = None
    current_step_lines = []
    current_step_switches_to_manual = False

    mode_lines = []
    waiting_for_split_mode_name = False

    def save_step():
        """Save a STEP using the mode active when that STEP began."""
        if current_step_id is not None:
            rows.append((
                current_step_id,
                list(current_step_lines),
                current_mode,
            ))

    def finish_step():
        """Save a STEP before applying its SINGLE STEP mode change."""
        nonlocal current_step_id
        nonlocal current_step_lines
        nonlocal current_step_switches_to_manual
        nonlocal current_mode

        save_step()

        if current_step_switches_to_manual:
            current_mode = "manual"

        current_step_id = None
        current_step_lines = []
        current_step_switches_to_manual = False

    def save_mode():
        """Save the current MODE event, if one exists."""
        if mode_lines:
            mode = _mode_name(mode_lines)

            if mode:
                event = _read_mode_event(mode_lines, warnings)

                if mode == "auto":
                    auto_date_time_status.append(event)

            mode_lines[:] = []

    def start_step(step_match, line):
        """Start a new STEP row."""
        nonlocal current_step_id
        nonlocal current_step_lines
        nonlocal current_step_switches_to_manual

        current_step_id = step_match.group(1)
        remainder = line[step_match.end():].strip()
        current_step_lines = [remainder] if remainder else []

        current_step_switches_to_manual = bool(
            re.search(
                r"\bSINGLE\s+STEP\b",
                remainder,
                re.IGNORECASE,
            )
        )

    for raw_line in lines:
        line = raw_line.strip()

        if not table_started:
            if re.search(r"\bSTEP\s+ID\b", line, re.IGNORECASE):
                table_started = True
            continue

        # OPERATING MODE AUTO/MANUAL changes the mode for subsequent rows.
        operating_match = OPERATING_MODE_RE.match(line)

        if operating_match:
            finish_step()
            save_mode()

            mode_match = MODE_NAME_RE.search(line[operating_match.end():])

            if mode_match:
                current_mode = mode_match.group(1).lower()

            mode_lines = []
            waiting_for_split_mode_name = False
            continue

        # MODE AUTO/MANUAL, including MODE and its name on separate lines.
        if _is_mode_start(line) or waiting_for_split_mode_name:
            finish_step()

            if _is_mode_start(line):
                save_mode()
                mode_lines = [line]
                mode_match = MODE_NAME_RE.search(line)

                if mode_match:
                    current_mode = mode_match.group(1).lower()
                    waiting_for_split_mode_name = False
                else:
                    waiting_for_split_mode_name = True

            else:
                mode_lines.append(line)
                mode_match = MODE_NAME_RE.search(line)

                if mode_match:
                    current_mode = mode_match.group(1).lower()
                    waiting_for_split_mode_name = False

            continue

        # Collect timestamp/status lines belonging to a MODE event.
        if mode_lines:
            step_match = STEP_ID_RE.match(line)

            if step_match:
                save_mode()
                start_step(step_match, line)
                continue

            mode_lines.append(line)
            continue

        step_match = STEP_ID_RE.match(line)

        if step_match:
            finish_step()
            start_step(step_match, line)

        elif current_step_id is not None:
            current_step_lines.append(line)

            # SINGLE STEP can also appear on a continuation line.
            if re.search(
                r"\bSINGLE\s+STEP\b",
                line,
                re.IGNORECASE,
            ):
                current_step_switches_to_manual = True

    finish_step()
    save_mode()

    for step_id, step_lines, step_mode in rows:
        if step_id in seen_ids:
            warnings.append(
                "Duplicate STEP ID " + step_id
                + " found in " + source_name
                + ", execution " + str(execution_number)
                + "; both occurrences are retained."
            )

        seen_ids.add(step_id)

        status = _status_near_timestamp(
            _combine_split_date_time(step_lines)
        )

        if status is None:
            warnings.append(
                "STEP " + step_id
                + " has no confidently detected status in "
                + source_name + ", execution "
                + str(execution_number) + "."
            )
            continue

        description, details, full_text = _description_and_reason(
            step_lines, warnings, step_id
        )

        overall_status[status].append(step_id)
        mode_status[step_mode][status].append(step_id)

        if status == "failure":
            failure_reasons.append({step_id: full_text})

    mode_executions = {
        "auto": {
            "date_time_status": auto_date_time_status,
            "success": mode_status["auto"]["success"],
            "failure": mode_status["auto"]["failure"],
            "progress": mode_status["auto"]["progress"],
            "suspend": mode_status["auto"]["suspend"],
        },
        "manual": {
            "success": mode_status["manual"]["success"],
            "failure": mode_status["manual"]["failure"],
            "progress": mode_status["manual"]["progress"],
            "suspend": mode_status["manual"]["suspend"],
        },
    }

    return overall_status, failure_reasons, mode_executions, warnings


def parse_pdf_text(text, source_name="unknown PDF"):
    """Parse procedure executions from extracted PDF text."""
    executions = []
    warnings = []
    blocks = split_procedure_blocks(text or "")

    if not blocks:
        warnings.append(
            source_name + ": no Procedure: headers were detected."
        )
        return executions, warnings

    for execution_number, block in enumerate(blocks, 1):
        name, date_time, duration = extract_metadata(block)

        if not name:
            warnings.append(
                source_name + ", execution " + str(execution_number)
                + ": procedure name was not detected."
            )

        if not date_time:
            warnings.append(
                source_name + ", execution " + str(execution_number)
                + ": procedure timestamp was not detected."
            )

        if duration is None:
            warnings.append(
                source_name + ", execution " + str(execution_number)
                + ": duration was not detected."
            )

        status, failure_reasons, modes, row_warnings = (
            _parse_procedure_steps(block, source_name, execution_number)
        )
        warnings.extend(row_warnings)

        if status["failure"]:
            final_status = "Failure"
            final_status_reason = failure_reasons
        else:
            final_status = "Success"
            final_status_reason = "None"

        executions.append({
            "Procedure Name": name,
            "date_time": date_time or "",
            "Dur": duration if duration is not None else 0,
            "Status": status,
            "final_status": final_status,
            "final_status_reason": final_status_reason,
            "mode_executions": modes,
        })

    return executions, warnings


def validate_execution(execution):
    """Return basic consistency problems for one execution."""
    issues = []
    status = execution.get("Status", {})

    for name in STATUS_NAMES:
        if not isinstance(status.get(name), list):
            issues.append(
                "Status key '" + name + "' is missing or invalid."
            )

    if status.get("failure") and execution.get("final_status") != "Failure":
        issues.append(
            "A failed STEP exists but final_status is not Failure."
        )

    if not status.get("failure") and execution.get("final_status") != "Success":
        issues.append(
            "No failed STEP exists but final_status is not Success."
        )

    return issues
    
