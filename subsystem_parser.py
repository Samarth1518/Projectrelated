# subsystem_parser.py
# Extract subsystem names and filenames from DOCX or text-based PDF.
# Compatible with Python 3.6.5.

import json
import os
import re
import tempfile

import fitz
import docx
from docx.text.paragraph import Paragraph
from docx.table import Table


SUBSYSTEM_RE = re.compile(
    r"^\s*Subsystem\s*:\s*(.*?)\s*$",
    re.IGNORECASE
)

VALID_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
INCOMPLETE_EXTENSION_RE = re.compile(r"\.(t|s)$", re.IGNORECASE)


def _clean_fragment(value):
    value = str(value or "").replace("\xa0", " ")
    value = value.replace("\r", "\n")
    value = value.strip()
    value = value.strip(" \t,;|")
    value = re.sub(r"^[•\-]+\s*", "", value)
    return value.strip()


def _is_ignored(value):
    lowered = value.lower().strip()

    if not lowered:
        return True

    if lowered.startswith("(*)"):
        return True

    if "follows" in lowered:
        return True

    if lowered in ("sem", "remarks", "filename", "file name"):
        return True

    if lowered.startswith("(*) sem"):
        return True

    return False


def _is_filename_candidate(value):
    value = _clean_fragment(value)

    if _is_ignored(value):
        return False

    # Recognised file extensions.
    if re.search(r"\.(tst|sh)$", value, re.IGNORECASE):
        return True

    # The filename column can also contain filenames without extensions.
    # Restrict these to one compact filename-like token.
    if " " in value or "\t" in value:
        return False

    return bool(VALID_FILENAME_RE.match(value))


def _extract_from_values(values):
    """
    Convert Filename-column cell values into filenames.

    Reconstruction is deliberately limited to line fragments inside the
    same table cell. It does not join the last text of one table row to the
    first text of the next row, because those may be separate filenames.
    """

    filenames = []

    for raw_value in values:
        raw_value = str(raw_value or "")
        raw_value = raw_value.replace("\xa0", " ")
        raw_value = raw_value.replace("\r", "\n")

        # A comma separates independent entries. Within each comma-delimited
        # entry, line breaks can represent a wrapped/split filename.
        comma_parts = raw_value.split(",")

        for comma_part in comma_parts:
            fragments = [
                _clean_fragment(line)
                for line in comma_part.split("\n")
            ]
            fragments = [
                item for item in fragments
                if item and not _is_ignored(item)
            ]

            pending = None

            for fragment in fragments:
                if pending is not None:
                    can_join = (
                        pending.endswith("-")
                        or bool(INCOMPLETE_EXTENSION_RE.search(pending))
                    )

                    if can_join:
                        combined = pending + fragment

                        if _is_filename_candidate(combined):
                            filenames.append(combined)
                            pending = None
                            continue

                        if INCOMPLETE_EXTENSION_RE.search(combined):
                            pending = combined
                            continue

                    if _is_filename_candidate(pending):
                        filenames.append(pending)
                    pending = None

                if fragment.endswith("-") or INCOMPLETE_EXTENSION_RE.search(fragment):
                    pending = fragment
                    continue

                if _is_filename_candidate(fragment):
                    filenames.append(fragment)

            if pending and _is_filename_candidate(pending):
                filenames.append(pending)

    # Preserve spelling and first-seen order while removing duplicates.
    unique = []
    seen = set()

    for filename in filenames:
        key = filename.lower()
        if key not in seen:
            seen.add(key)
            unique.append(filename)

    return unique


def _normalise_header(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z]", "", value)
    return value


def _find_filename_column(rows):
    """
    Find the row containing the Filename header and return
    (header_row_index, filename_column_index).
    """

    for row_index, row in enumerate(rows[:8]):
        for column_index, cell in enumerate(row):
            if _normalise_header(cell.text) == "filename":
                return row_index, column_index

    return None, None


def _add_table_filenames(result, subsystem_name, table):
    if not subsystem_name:
        return

    rows = table.rows
    row_values = []

    for row in rows:
        row_values.append([cell.text for cell in row.cells])

    header_row, filename_column = _find_filename_column(rows)

    if header_row is None:
        return

    values = []

    for row in row_values[header_row + 1:]:
        if filename_column < len(row):
            values.append(row[filename_column])

    extracted = _extract_from_values(values)

    if subsystem_name not in result:
        result[subsystem_name] = []

    existing = set(item.lower() for item in result[subsystem_name])

    for filename in extracted:
        if filename.lower() not in existing:
            result[subsystem_name].append(filename)
            existing.add(filename.lower())


def parse_docx(path):
    """Read paragraphs and tables in their original document order."""

    document = docx.Document(path)
    result = {}
    current_subsystem = None

    body = document.element.body

    for child in body.iterchildren():
        tag = child.tag.lower()

        if tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()

            match = SUBSYSTEM_RE.match(text)
            if match:
                current_subsystem = match.group(1).strip()
                if current_subsystem and current_subsystem not in result:
                    result[current_subsystem] = []

        elif tag.endswith("}tbl"):
            table = Table(child, document)
            _add_table_filenames(result, current_subsystem, table)

    _validate_result(result, path)
    return result


def _split_pdf_columns(line):
    # Text-based PDF fallback. Most exported tables preserve columns using
    # repeated spaces or tabs. This is not intended for scanned PDFs.
    if "\t" in line:
        return [part.strip() for part in re.split(r"\t+", line.strip())]
    return [part.strip() for part in re.split(r"\s{2,}", line.strip())]


def parse_text_pdf(path):
    """
    Read selectable text from a PDF and extract rows using the text layout.

    PDF extraction is layout-dependent. The parser identifies a Filename
    header in a multi-column line and uses that column position in following
    rows. Scanned/image-only PDFs are not supported.
    """

    document = fitz.open(path)
    result = {}
    current_subsystem = None
    active_filename_index = None
    collecting_values = []

    def flush_values():
        if current_subsystem and collecting_values:
            extracted = _extract_from_values(collecting_values)
            if current_subsystem not in result:
                result[current_subsystem] = []
            existing = set(x.lower() for x in result[current_subsystem])
            for item in extracted:
                if item.lower() not in existing:
                    result[current_subsystem].append(item)
                    existing.add(item.lower())
            del collecting_values[:]

    try:
        for page_number in range(document.page_count):
            page = document.load_page(page_number)
            text = page.get_text("text") or ""

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                subsystem_match = SUBSYSTEM_RE.match(line)
                if subsystem_match:
                    flush_values()
                    current_subsystem = subsystem_match.group(1).strip()
                    active_filename_index = None
                    if current_subsystem and current_subsystem not in result:
                        result[current_subsystem] = []
                    continue

                columns = _split_pdf_columns(line)
                normalised_columns = [
                    _normalise_header(value) for value in columns
                ]

                if "filename" in normalised_columns:
                    flush_values()
                    active_filename_index = normalised_columns.index("filename")
                    continue

                if current_subsystem and active_filename_index is not None:
                    if len(columns) > active_filename_index:
                        collecting_values.append(columns[active_filename_index])

        flush_values()

    finally:
        document.close()

    _validate_result(result, path)
    return result


def _validate_result(result, source_path):
    if not isinstance(result, dict) or not result:
        raise ValueError(
            "No subsystem headings and Filename tables were found in: "
            + os.path.basename(source_path)
        )

    valid = {}
    for subsystem, filenames in result.items():
        subsystem = str(subsystem).strip()
        if subsystem:
            valid[subsystem] = list(filenames)

    if not any(valid.values()):
        raise ValueError(
            "Subsystem headings were found, but no filenames were extracted. "
            "Please check that the table contains a Filename header."
        )


def parse_subsystem_document(path):
    """Select the parser based on the uploaded file extension."""

    extension = os.path.splitext(path)[1].lower()

    if extension == ".docx":
        return parse_docx(path)

    if extension == ".pdf":
        return parse_text_pdf(path)

    raise ValueError("Only DOCX and text-based PDF files are supported.")


def save_subsystems_json(subsystems, destination_path):
    """
    Safely replace subsystems.json:
    validate, write a temporary JSON file, then atomically replace the old one.
    """

    if not isinstance(subsystems, dict) or not subsystems:
        raise ValueError("The extracted subsystem configuration is empty.")

    for name, filenames in subsystems.items():
        if not str(name).strip() or not isinstance(filenames, list):
            raise ValueError("Invalid subsystem configuration structure.")

    directory = os.path.dirname(os.path.abspath(destination_path))
    temporary_path = None

    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="subsystems_",
            dir=directory,
            delete=False
        )
        temporary_path = handle.name

        with handle:
            json.dump(
                subsystems,
                handle,
                indent=4,
                ensure_ascii=False
            )

        # Verify the temporary file before replacing the valid configuration.
        with open(temporary_path, "r") as check_file:
            checked_data = json.load(check_file)

        if not isinstance(checked_data, dict) or not checked_data:
            raise ValueError("Generated subsystem JSON failed validation.")

        os.replace(temporary_path, destination_path)
        temporary_path = None

    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)
