PDF to JSON project - table file update
=======================================

FOLDER LAYOUT (same as before, plus one new file)
  JSON Project/
    main.py            <- REPLACE with the new one
    pdf_parser.py      <- UNCHANGED (identical to your current file; no need to touch)
    table_builder.py   <- NEW, add this
    input/             <- put PDFs here (as before)
    output/            <- results appear here (as before)

STEPS
  1. Make a COPY of your whole project folder first (backup).
  2. Put table_builder.py into the project folder.
  3. Replace main.py with the new main.py.
  4. Leave pdf_parser.py as it is.
  5. Run main.py as usual.

RESULT: every run creates two files with the SAME time in output/
  output_2026-11-09_18-04-33.json   <- your original file (unchanged format/content)
  table_2026-11-09_18-04-33.json    <- NEW table file

WHAT CHANGED IN main.py (only these 4 things)
  1. Safe import of table_builder at the top (if missing, program still works).
  2. Old-file cleanup also removes old table_*.json (still only inside output/).
  3. After the original output is saved, a separate step writes the table file.
     If that step fails you only get a WARNING; the original output is not affected.
  4. One extra print line: "Table file: ...".

WHAT IS NOT CHANGED
  pdf_parser.py, PDF reading, parsing, output_*.json content, folders, filenames.

TABLE FILE CONTENTS
  procedure_summary : one row per procedure
      procedure_name, total_executions, success_runs, failure_runs,
      latest_date, latest_time, latest_date_time, latest_mode,
      latest_final_status, modes_used, total_duration_sec
  table : one row per execution
      procedure_name, run_no, date, time, date_time, duration_sec, mode,
      final_status, total_steps, success_count, failure_count, suspend_count,
      progress_count, failed_steps, failure_reason, auto_status
  Insights : copied from the original output

MODE VALUES
  Auto           = only AUTO steps ran
  Manual         = only MANUAL steps ran
  Auto + Manual  = both ran in that execution
