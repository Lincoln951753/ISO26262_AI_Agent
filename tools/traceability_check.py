"""Structure-only SG -> FSR -> TSR traceability checker (Assignment 2 MVP).

This tool checks project-defined Excel columns and ID links. It does not read
ISO 26262 clauses or determine compliance. Output keeps the existing Agent's
JSON contract: {status, summary, issues} or {status, message}.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


DATA_DIR = Path(__file__).resolve().parent.parent / "test_data"
REQUIRED_COLUMNS = {
    "SG": ("ID", "Description"),
    "FSR": ("ID", "SG_ID", "Description"),
    "TSR": ("ID", "FSR_ID", "Description"),
}


def _error(message: str) -> dict[str, Any]:
    return {"status": "error", "message": message}


def _resolve_input(file_path: str) -> Path | None:
    """Allow only a .xlsx file inside this project's test_data folder.

    Accepts a filename, test_data/filename.xlsx, or an absolute path within
    test_data (the existing Agent passes the latter). Rejects traversal and
    symlinks pointing outside test_data.
    """
    if not isinstance(file_path, str) or not file_path or "\x00" in file_path:
        return None
    raw = Path(file_path)
    if raw.suffix.lower() != ".xlsx":
        return None
    if raw.is_absolute():
        candidate = raw
    elif len(raw.parts) == 1:
        candidate = DATA_DIR / raw
    elif len(raw.parts) == 2 and raw.parts[0] == "test_data":
        candidate = DATA_DIR / raw.parts[1]
    else:
        return None
    resolved = candidate.resolve(strict=False)
    if resolved.parent != DATA_DIR.resolve(strict=False):
        return None
    return resolved


def _issue(kind: str, record: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "type": kind,
        "requirement": record.get("ID") or f"(missing ID, row {record['_row']})",
        "row": record["_row"],
        "message": message,
    }


def traceability_check(file_path: str) -> dict[str, Any]:
    """Inspect SG, FSR and TSR sheets for structural completeness and links.

    A successful run may contain issues; 'status=success' only means the
    workbook was parsed and checked. Issues do not establish ISO 26262
    compliance or noncompliance.
    """
    path = _resolve_input(file_path)
    if path is None:
        return _error("Invalid file path: only .xlsx files in test_data are allowed")
    if not path.is_file():
        return _error(f"File not found: {path}")

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            data: dict[str, list[dict[str, Any]]] = {}
            for sheet_name, required in REQUIRED_COLUMNS.items():
                if sheet_name not in workbook.sheetnames:
                    return _error(f"Missing sheet: {sheet_name}")
                worksheet = workbook[sheet_name]
                iterator = worksheet.iter_rows(values_only=True)
                header_values = next(iterator, None)
                if header_values is None:
                    return _error(f"Empty sheet: {sheet_name}")
                headers = [str(v).strip() if v is not None else "" for v in header_values]
                missing = [column for column in required if column not in headers]
                if missing:
                    # Retain existing FC-02 wording for compatibility.
                    return _error(f"{sheet_name} missing columns: {missing}")
                duplicated = [column for column in required if headers.count(column) > 1]
                if duplicated:
                    return _error(f"{sheet_name} duplicate columns: {duplicated}")
                positions = {column: headers.index(column) for column in required}
                records: list[dict[str, Any]] = []
                for row_number, values in enumerate(iterator, start=2):
                    record = {
                        column: (
                            str(values[position]).strip()
                            if position < len(values) and values[position] is not None
                            else ""
                        )
                        for column, position in positions.items()
                    }
                    if not any(record.values()):
                        continue  # Skip entirely empty spreadsheet rows.
                    record["_row"] = row_number
                    records.append(record)
                data[sheet_name] = records

            if not any(data.values()):
                return _error("No requirement data found in SG, FSR or TSR")

            issues: list[dict[str, Any]] = []
            id_counts = {
                sheet: Counter(row["ID"] for row in rows if row["ID"])
                for sheet, rows in data.items()
            }
            unique_ids = {
                sheet: {id_ for id_, count in counts.items() if count == 1}
                for sheet, counts in id_counts.items()
            }

            # Report data quality problems, including row numbers.
            for sheet, records in data.items():
                first_seen: dict[str, int] = {}
                for record in records:
                    id_ = record["ID"]
                    if not id_:
                        issues.append(_issue("MISSING_ID", record, f"{sheet} row {record['_row']} has an empty ID"))
                    elif id_ in first_seen:
                        issues.append(_issue(
                            f"DUPLICATE_{sheet}_ID", record,
                            f"{sheet} ID {id_} is duplicated (first at row {first_seen[id_]})",
                        ))
                    else:
                        first_seen[id_] = record["_row"]
                    if not record["Description"]:
                        issues.append(_issue(
                            "MISSING_DESCRIPTION", record,
                            f"{sheet} row {record['_row']} has an empty Description",
                        ))

            referenced_sg: set[str] = set()
            referenced_fsr: set[str] = set()

            for fsr in data["FSR"]:
                parent = fsr["SG_ID"]
                if not parent or parent not in id_counts["SG"]:
                    issues.append(_issue(
                        "INVALID_SG_REFERENCE", fsr,
                        f"FSR {fsr['ID'] or '(missing ID)'} has no valid SG",
                    ))
                elif parent not in unique_ids["SG"]:
                    issues.append(_issue(
                        "AMBIGUOUS_SG_REFERENCE", fsr,
                        f"FSR {fsr['ID']} refers to duplicate SG ID {parent}",
                    ))
                else:
                    # The SG has an FSR row referring to it, even if that FSR's
                    # own ID is duplicated or blank; report that separately.
                    referenced_sg.add(parent)

            for tsr in data["TSR"]:
                parent = tsr["FSR_ID"]
                if not parent or parent not in id_counts["FSR"]:
                    issues.append(_issue(
                        "INVALID_FSR_REFERENCE", tsr,
                        f"TSR {tsr['ID'] or '(missing ID)'} has no valid FSR",
                    ))
                elif parent not in unique_ids["FSR"]:
                    issues.append(_issue(
                        "AMBIGUOUS_FSR_REFERENCE", tsr,
                        f"TSR {tsr['ID']} refers to duplicate FSR ID {parent}",
                    ))
                else:
                    # A TSR row refers to this FSR even if its own ID is
                    # duplicated or blank; do not report a false missing link.
                    referenced_fsr.add(parent)

            # For the "without" checks, a uniquely identified parent with a
            # referring child row counts as linked. Invalid child identifiers
            # are reported as separate issues instead of false missing links.
            for sg in data["SG"]:
                if sg["ID"] in unique_ids["SG"] and sg["ID"] not in referenced_sg:
                    issues.append(_issue("SG_WITHOUT_FSR", sg, f"SG {sg['ID']} has no FSR"))
            for fsr in data["FSR"]:
                if fsr["ID"] in unique_ids["FSR"] and fsr["ID"] not in referenced_fsr:
                    issues.append(_issue("FSR_WITHOUT_TSR", fsr, f"FSR {fsr['ID']} has no TSR"))

            return {
                "status": "success",
                "summary": {
                    "SG_count": len(data["SG"]),
                    "FSR_count": len(data["FSR"]),
                    "TSR_count": len(data["TSR"]),
                    "issue_count": len(issues),
                },
                "issues": issues,
            }
        finally:
            workbook.close()
    except Exception as exc:
        return _error(f"Excel parsing failed: {type(exc).__name__}: {exc}")
