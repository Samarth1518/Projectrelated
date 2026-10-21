# main.py
# Main program for converting every PDF in input/ into one JSON file.
# Compatible with Python 3.6 and PyMuPDF 1.18.x.

import glob
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime

import fitz

from pdf_parser import parse_pdf_text, normalize_procedure_name, validate_execution


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def get_pdf_document(path):
    """Open a PDF using the PyMuPDF API available in this environment."""
    return fitz.open(path)


def get_page_count(document):
    """Support both older and newer PyMuPDF page-count properties."""
    if hasattr(document, "pageCount"):
        return document.pageCount
    return document.page_count


def get_page(document, page_number):
    """Support both older and newer PyMuPDF page-loading methods."""
    if hasattr(document, "loadPage"):
        return document.loadPage(page_number)
    return document.load_page(page_number)


def get_page_text(page):
    """Extract selectable text from one page."""
    if hasattr(page, "getText"):
        return page.getText("text")
    return page.get_text("text")


def read_pdf_text_incrementally(path):
    """
    Read one page at a time, instead of asking PyMuPDF to extract the whole
    document in one operation. The text is kept together so procedure rows
    that continue across page boundaries can still be parsed as one sequence.
    """
    document = None
    page_text_parts = []
    page_count = 0

    try:
        document = get_pdf_document(path)
        page_count = get_page_count(document)

        for page_number in range(page_count):
            page = get_page(document, page_number)
            page_text_parts.append(get_page_text(page) or "")

            # Keep a page boundary, but do not reset procedure or mode context.
            page_text_parts.append("\n")

    finally:
        if document is not None:
            document.close()

    return "".join(page_text_parts), page_count


def list_input_pdfs():
    """Return all PDF files directly inside the input folder."""
    pattern = os.path.join(INPUT_DIR, "*.pdf")
    return sorted(glob.glob(pattern), key=lambda path: os.path.basename(path).lower())


def ensure_folders_exist():
    """Check the folders that are part of the agreed project layout."""
    if not os.path.isdir(INPUT_DIR):
        raise RuntimeError(
            "The input folder was not found:\n" + INPUT_DIR
        )

    if not os.path.isdir(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)


def add_execution(output_data, execution, pdf_name):
    """Group an execution under its procedure name."""
    procedure_name = (execution.get("Procedure Name") or "").strip()

    if not procedure_name:
        procedure_name = "UNKNOWN_PROCEDURE_" + str(len(output_data) + 1)
        print(
            "WARNING: A procedure name could not be detected in "
            + pdf_name + ". It was placed under " + procedure_name + "."
        )

    normalized_name = normalize_procedure_name(procedure_name)

    # Reuse the existing key if the same procedure name appears with different
    # capitalization or extra spaces in another execution.
    existing_key = None
    for key in output_data.keys():
        if key != "Insights" and normalize_procedure_name(key) == normalized_name:
            existing_key = key
            break

    if existing_key is None:
        existing_key = procedure_name
        output_data[existing_key] = {"procedures": []}

    clean_execution = OrderedDict()
    clean_execution["date_time"] = execution.get("date_time", "")
    clean_execution["Dur"] = execution.get("Dur", 0)
    clean_execution["Status"] = execution.get("Status", {})
    clean_execution["final_status"] = execution.get("final_status", "Success")
    clean_execution["final_status_reason"] = execution.get(
        "final_status_reason", "None"
    )
    clean_execution["mode_executions"] = execution.get("mode_executions", {})

    output_data[existing_key]["procedures"].append(clean_execution)


def remove_old_generated_outputs():
    """Remove only files matching this program's generated-output filename."""
    pattern = os.path.join(OUTPUT_DIR, "output_*.json")
    for path in glob.glob(pattern):
        if os.path.isfile(path):
            os.remove(path)


def validate_output_data(output_data):
    """Check basic JSON structure before replacing the previous output."""
    if "Insights" not in output_data:
        raise ValueError("The output is missing the global Insights object.")

    for procedure_name, procedure_group in output_data.items():
        if procedure_name == "Insights":
            continue

        if not isinstance(procedure_group, dict):
            raise ValueError("Invalid procedure group: " + str(procedure_name))

        if not isinstance(procedure_group.get("procedures"), list):
            raise ValueError(
                "Procedure group has no procedures list: " + str(procedure_name)
            )

        for execution in procedure_group["procedures"]:
            issues = validate_execution(execution)
            if issues:
                raise ValueError(
                    "Output validation failed for " + str(procedure_name) +
                    ": " + "; ".join(issues)
                )


def write_output_safely(output_data):
    """
    Write and validate a temporary JSON file first. Only after it succeeds,
    remove the previous generated JSON and rename the new file into place.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_name = "output_" + timestamp + ".json"
    final_path = os.path.join(OUTPUT_DIR, output_name)
    temporary_path = final_path + ".tmp"

    try:
        with open(temporary_path, "w", encoding="utf-8") as output_file:
            json.dump(
                output_data,
                output_file,
                indent=4,
                ensure_ascii=False,
            )
            output_file.write("\n")

        # Re-open the temporary file to ensure the JSON can be read.
        with open(temporary_path, "r", encoding="utf-8") as check_file:
            json.load(check_file)

        # Preserve the previous output until the new file has been written
        # and successfully parsed as JSON.
        remove_old_generated_outputs()
        os.rename(temporary_path, final_path)

    except Exception:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        raise

    return final_path


def main():
    print("=" * 60)
    print("PDF to JSON converter")
    print("=" * 60)

    try:
        ensure_folders_exist()
    except Exception as error:
        print("ERROR:", error)
        return 1

    pdf_paths = list_input_pdfs()

    if not pdf_paths:
        print("No PDF files were found in the input folder:")
        print(INPUT_DIR)
        print("Put new_dataset.pdf (and any other PDFs) inside input/ and run again.")
        return 1

    output_data = OrderedDict()
    pdf_names = []
    total_pages_read = 0
    total_procedures = 0
    total_warnings = 0
    pdfs_read = 0

    for pdf_path in pdf_paths:
        pdf_name = os.path.basename(pdf_path)
        print("\nReading PDF:", pdf_name)

        try:
            pdf_text, page_count = read_pdf_text_incrementally(pdf_path)
            total_pages_read += page_count
            pdf_names.append(pdf_name)

            executions, warnings = parse_pdf_text(pdf_text, pdf_name)
            pdfs_read += 1

            if not executions:
                print("WARNING: No procedure executions were extracted from", pdf_name)

            for execution in executions:
                add_execution(output_data, execution, pdf_name)
                total_procedures += 1

            for warning in warnings:
                total_warnings += 1
                print("WARNING:", warning)

            print(
                "Finished:", pdf_name,
                "| Pages:", page_count,
                "| Procedure executions:", len(executions),
                "| Warnings:", len(warnings),
            )

        except Exception as error:
            print("ERROR: Could not process", pdf_name)
            print("Reason:", str(error))
            print("The other PDFs will still be processed.")

    if pdfs_read == 0:
        print("\nNo PDF was processed successfully. No new output was created.")
        return 1

    # Insights is one global object, added once at the end.
    output_data["Insights"] = OrderedDict([
        ("Total PDFs read", pdfs_read),
        ("PDF names", pdf_names),
        ("Total Pages read", total_pages_read),
    ])

    try:
        validate_output_data(output_data)
        output_path = write_output_safely(output_data)
    except Exception as error:
        print("\nERROR: The output could not be safely saved.")
        print("Reason:", str(error))
        print("Any previous generated JSON was kept if writing had not completed.")
        return 1

    print("\n" + "=" * 60)
    print("Conversion finished.")
    print("PDFs read:", pdfs_read)
    print("Total pages read:", total_pages_read)
    print("Procedure executions extracted:", total_procedures)
    print("Warnings raised:", total_warnings)
    print("Output file:", output_path)
    print("=" * 60)

    if total_warnings:
        print(
            "\nPlease review the WARNING messages above and spot-check the JSON "
            "against the PDF before using it."
        )
    else:
        print(
            "\nPlease still spot-check a few records against the source PDF "
            "before relying on the output."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
