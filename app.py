# app.py
# Flask application for Satellite Testing Dashboard
# Compatible with Python 3.6.5

import os
import glob
import subprocess
import sys

from datetime import datetime
from flask import Flask, render_template, request, flash
from werkzeug.utils import secure_filename

from dashboard import process_dashboard
from subsystem_parser import (
    parse_subsystem_document,
    save_subsystems_json
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SUBSYSTEM_FILE = os.path.join(BASE_DIR, "subsystems.json")

ALLOWED_PDF_EXTENSIONS = set(["pdf"])
ALLOWED_CONFIG_EXTENSIONS = set(["docx", "pdf"])

app = Flask(__name__)
app.secret_key = "satellite_dashboard_local_key"


def create_folders():
    for folder in [INPUT_DIR, OUTPUT_DIR]:
        if not os.path.isdir(folder):
            os.makedirs(folder)


def has_allowed_extension(filename, allowed_extensions):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in allowed_extensions
    )


def get_latest_json():
    files = glob.glob(os.path.join(OUTPUT_DIR, "output_*.json"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def clear_old_input_pdfs():
    for path in glob.glob(os.path.join(INPUT_DIR, "*.pdf")):
        if os.path.isfile(path):
            os.remove(path)


def run_pdf_converter():
    main_path = os.path.join(BASE_DIR, "main.py")

    result = subprocess.run(
        [sys.executable, main_path],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr or result.stdout or "PDF conversion failed."
        )

    return result.stdout


def validate_date_selection(date_filter, start_date, end_date):
    if date_filter == "overall":
        return

    if date_filter != "date_range":
        raise ValueError("Invalid date selection.")

    if not start_date or not end_date:
        raise ValueError("Please select both start and end dates.")

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Please provide valid start and end dates.")

    if start > end:
        raise ValueError("Start date cannot be later than end date.")


@app.route("/", methods=["GET", "POST"])
def index():
    create_folders()

    dashboard_data = None
    project_name = ""
    date_filter = "overall"
    start_date = ""
    end_date = ""

    if request.method == "POST":
        project_name = request.form.get("project_name", "").strip()
        date_filter = request.form.get("date_filter", "overall").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()

        uploaded_pdfs = request.files.getlist("pdf_files")
        config_file = request.files.get("subsystem_file")

        temporary_config_path = None

        try:
            if not project_name:
                raise ValueError("Please enter a project name.")

            validate_date_selection(date_filter, start_date, end_date)

            valid_pdfs = [
                item for item in uploaded_pdfs
                if item and item.filename
                and has_allowed_extension(
                    item.filename, ALLOWED_PDF_EXTENSIONS
                )
            ]

            if not valid_pdfs:
                raise ValueError("Please select at least one valid test-report PDF.")

            if not config_file or not config_file.filename:
                raise ValueError("Please upload a subsystem configuration DOCX or PDF.")

            if not has_allowed_extension(
                    config_file.filename, ALLOWED_CONFIG_EXTENSIONS):
                raise ValueError(
                    "Subsystem configuration must be a DOCX or PDF file."
                )

            config_filename = secure_filename(config_file.filename)
            if not config_filename:
                raise ValueError("The subsystem configuration filename is invalid.")

            temporary_config_path = os.path.join(
                INPUT_DIR, "uploaded_subsystem_config" +
                os.path.splitext(config_filename)[1].lower()
            )
            config_file.save(temporary_config_path)

            # Parse first. If parsing fails, the existing subsystems.json
            # remains untouched.
            parsed_subsystems = parse_subsystem_document(
                temporary_config_path
            )

            if not parsed_subsystems:
                raise ValueError("No valid subsystem data was extracted.")

            # Replace the report batch, preserving the existing converter.
            clear_old_input_pdfs()

            saved_count = 0
            for uploaded_file in valid_pdfs:
                filename = secure_filename(uploaded_file.filename)
                if not filename:
                    continue

                save_path = os.path.join(INPUT_DIR, filename)
                uploaded_file.save(save_path)
                saved_count += 1

            if saved_count == 0:
                raise RuntimeError("No valid PDF files could be saved.")

            run_pdf_converter()

            json_path = get_latest_json()
            if json_path is None:
                raise RuntimeError(
                    "The converter did not generate an output JSON file."
                )

            # Use the newly parsed configuration in memory first. The old
            # subsystems.json is replaced only after dashboard processing works.
            dashboard_data = process_dashboard(
                json_path,
                project_name,
                date_filter,
                start_date if date_filter == "date_range" else None,
                end_date if date_filter == "date_range" else None,
                parsed_subsystems
            )

            save_subsystems_json(parsed_subsystems, SUBSYSTEM_FILE)

            flash(
                str(saved_count) +
                " PDF file(s) processed. Subsystem configuration extracted: " +
                str(len(parsed_subsystems)) + " subsystem(s)."
            )

        except Exception as error:
            dashboard_data = None
            flash("Error: " + str(error))

        finally:
            if temporary_config_path and os.path.exists(temporary_config_path):
                try:
                    os.remove(temporary_config_path)
                except OSError:
                    pass

    return render_template(
        "index.html",
        dashboard_data=dashboard_data,
        project_name=project_name,
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date
    )


if __name__ == "__main__":
    create_folders()
    print("=" * 50)
    print("SATELLITE TESTING DASHBOARD")
    print("=" * 50)
    print("Open your browser at http://127.0.0.1:5000")
    print("Press CTRL+C to stop the server.")
    app.run(host="127.0.0.1", port=5000, debug=False)
