# pdf_parser.py
# Extract procedure and STEP information from the PDF text.
# Compatible with Python 3.6.

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

# A valid STEP ID starts a row. 99.999 is intentionally not excluded here:
# it is handled like a STEP because the agreed rule is to retain STEP rows.
STEP_ID_RE = re.compile(r"^\s*(\d{2}\.\d{3,4})\b")
MODE_RE = re.compile(r"^\s*MODE\b", re.IGNORECASE)
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
DURATION_RE = re.compile(r"\bDur\s*:\s*(\d+(?:\.\d+)?)\s*\(s\)", re.IGNORECASE)
STATUS_WORD_RE = re.compile(r"\b(Success|Failure|Suspend|Progress)\b", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"^[\s\-_=*|]+$")


def normalize_procedure_name(name):
    """Normalize a procedure name for grouping."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def normalize_datetime(value):
    """Convert a supported date/time string to YYYY-MM-DD HH:MM:SS.mmm."""
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
    """
    Join a date at the end of one line and a time at the start of the next
    line. This helps with the split timestamps visible in the sample PDF.
    """
    combined = []
    index = 0

    while index < len(lines):
        line = lines[index]
        date_match = DATE_RE.search(line)

        if date_match and not DATE_TIME_RE.search(line) and index + 1 < len(lines):
            next_line = lines[index + 1]
            time_match = TIME_RE.search(next_line)
            if time_match:
                before_date = line[:date_match.start()]
                date_text = date_match.group(0)
                time_text = time_match.group(0)
                after_time = next_line[time_match.end():]
                combined.append(
                    before_date + date_text + " " + time_text + after_time
                )
                index += 2
                continue

        combined.append(line)
        index += 1

    return combined


def split_procedure_blocks(text):
    """Split the document whenever a new Procedure: header begins."""
    matches = list(re.finditer(r"\bProcedure\s*:", text or "", re.IGNORECASE))
    blocks = []

    for index, match in enumerate(matches):
        start = match.start()
        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(text)
        blocks.append(text[start:end])

    return blocks


def extract_metadata(block):
    """Read procedure name, header timestamp and duration."""
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
        # Python round() uses ties-to-even. The duration is non-negative;
        # adding 0.5 gives the requested nearest-whole-number behavior.
        duration = int(float(duration_match.group(1)) + 0.5)

    return name, date_time, duration


def _is_mode_start(line):
    """Recognize a MODE marker, including MODE and AUTO on one line."""
    return bool(MODE_RE.match(line or ""))


def _mode_name(lines):
    """Find AUTO or MANUAL even when it is on the line after MODE."""
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
    """
    Find the status associated with the timestamped part of a STEP/MODE row.
    Words in the description before the timestamp are not considered.
    """
    timestamp_seen = False

    for line in lines:
        date_match = DATE_RE.search(line)
        time_match = TIME_RE.search(line)

        if date_match or time_match:
            timestamp_seen = True

            # A status after the time on this same line is the strongest match.
            if time_match:
                suffix = line[time_match.end():]
                matches = list(STATUS_WORD_RE.finditer(suffix))
                if matches:
                    return matches[-1].group(1).lower()

            # If the timestamp is split across lines, status may be on a
            # nearby line after the timestamp.
            continue

        if timestamp_seen:
            stripped = line.strip()
            standalone = re.match(
                r"^(Success|Failure|Suspend|Progress)\b",
                stripped,
                re.IGNORECASE,
            )
            if standalone:
                return standalone.group(1).lower()

    return None


def _description_and_reason(step_lines, warnings, step_id):
    """
    Extract the STEP description and any continuation text.

    The first timestamp separates the main description from later details.
    Continuation lines are retained; the caller uses them in failure reasons
    only when this STEP's actual status is Failure.
    """
    lines = _combine_split_date_time(step_lines)
    description_parts = []
    detail_parts = []
    timestamp_seen = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or SEPARATOR_RE.fullmatch(line):
            continue

        # Remove the STEP ID if it appears again in a continuation line.
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

            # Text after the timestamp may contain the status and/or extra
            # text. Remove the date/time and only the trailing status word.
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

        # A status on its own line is metadata, not explanation text.
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

    description = re.sub(r"\s+", " ", " ".join(description_parts)).strip()
    details = re.sub(r"\s+", " ", " ".join(detail_parts)).strip()

    if description and details:
        full_text = description + ", " + details
    else:
        full_text = description or details

    if not full_text:
        warnings.append(
            "STEP " + step_id + " has no confidently extracted description."
        )

    return description, details, full_text


def _read_mode_event(mode_lines, warnings):
    """Read timestamp and status from a MODE AUTO/MANUAL row."""
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
    """Extract STEP rows and mode assignments from one procedure block."""
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
    mode_lines = []
    waiting_for_split_mode_name = False

    def save_step():
        if current_step_id is not None:
            rows.append(("step", current_step_id, list(current_step_lines), current_mode))

    def save_mode():
        if mode_lines:
            mode = _mode_name(mode_lines)
            if mode:
                event = _read_mode_event(mode_lines, warnings)
                if mode == "auto":
                    auto_date_time_status.append(event)
            mode_lines[:] = []

    for raw_line in lines:
        line = raw_line.strip()

        if not table_started:
            if re.search(r"\bSTEP\s+ID\b", line, re.IGNORECASE):
                table_started = True
            continue

        # Handle a mode marker, including a line that contains only MODE.
        if _is_mode_start(line) or waiting_for_split_mode_name:
            save_step()
            current_step_id = None
            current_step_lines = []

            if _is_mode_start(line):
                save_mode()
                mode_lines = [line]
                mode_match = MODE_NAME_RE.search(line)
                if not mode_match:
                    waiting_for_split_mode_name = True
                else:
                    waiting_for_split_mode_name = False
                    current_mode = mode_match.group(1).lower()
            else:
                mode_lines.append(line)
                mode_match = MODE_NAME_RE.search(line)
                if mode_match:
                    waiting_for_split_mode_name = False
                    current_mode = mode_match.group(1).lower()
            continue

        # If a mode row is being collected, retain its split timestamp/status
        # lines until a new STEP or another MODE marker starts.
        if mode_lines:
            step_match = STEP_ID_RE.match(line)
            if step_match:
                save_mode()
                current_step_id = step_match.group(1)
                remainder = line[step_match.end():].strip()
                current_step_lines = [remainder] if remainder else []
                continue
            mode_lines.append(line)
            continue

        step_match = STEP_ID_RE.match(line)
        if step_match:
            save_step()
            current_step_id = step_match.group(1)
            remainder = line[step_match.end():].strip()
            current_step_lines = [remainder] if remainder else []
        elif current_step_id is not None:
            current_step_lines.append(line)

    save_step()
    save_mode()

    for row_type, step_id, step_lines, step_mode in rows:
        if step_id in seen_ids:
            warnings.append(
                "Duplicate STEP ID " + step_id +
                " found in " + source_name + ", execution " +
                str(execution_number) + "; both occurrences are retained."
            )
        seen_ids.add(step_id)

        status = _status_near_timestamp(_combine_split_date_time(step_lines))
        if status is None:
            warnings.append(
                "STEP " + step_id + " has no confidently detected status in " +
                source_name + ", execution " + str(execution_number) + "."
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
    """
    Parse extracted text from one PDF.

    Returns:
        executions: list of procedure execution dictionaries
        warnings: list of extraction issues that need checking
    """
    executions = []
    warnings = []
    blocks = split_procedure_blocks(text or "")

    if not blocks:
        warnings.append(source_name + ": no Procedure: headers were detected.")
        return executions, warnings

    for execution_number, block in enumerate(blocks, 1):
        name, date_time, duration = extract_metadata(block)

        if not name:
            warnings.append(
                source_name + ", execution " + str(execution_number) +
                ": procedure name was not detected."
            )
        if not date_time:
            warnings.append(
                source_name + ", execution " + str(execution_number) +
                ": procedure timestamp was not detected."
            )
        if duration is None:
            warnings.append(
                source_name + ", execution " + str(execution_number) +
                ": duration was not detected."
            )

        status, failure_reasons, modes, row_warnings = _parse_procedure_steps(
            block, source_name, execution_number
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
    """Return basic consistency problems for one parsed execution."""
    issues = []
    status = execution.get("Status", {})

    for name in STATUS_NAMES:
        if not isinstance(status.get(name), list):
            issues.append("Status key '" + name + "' is missing or invalid.")

    if status.get("failure") and execution.get("final_status") != "Failure":
        issues.append("A failed STEP exists but final_status is not Failure.")

    if not status.get("failure") and execution.get("final_status") != "Success":
        issues.append("No failed STEP exists but final_status is not Success.")

    return issues
