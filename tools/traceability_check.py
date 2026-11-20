
from pathlib import Path
from openpyxl import load_workbook


def traceability_check(file_path: str) -> dict:
    """
    檢查 Excel 中 SG、FSR、TSR 的追溯關係。

    Excel 工作表：
    SG  : ID, Description
    FSR : ID, SG_ID, Description
    TSR : ID, FSR_ID, Description
    """

    path = Path(file_path)

    # Failure Case 1：找不到檔案
    if not path.is_file():
        return {
            "status": "error",
            "message": f"File not found: {file_path}"
        }

    required_columns = {
        "SG": ["ID", "Description"],
        "FSR": ["ID", "SG_ID", "Description"],
        "TSR": ["ID", "FSR_ID", "Description"]
    }

    try:
        wb = load_workbook(path, read_only=True, data_only=True)

        try:
            data = {}

            for sheet_name, columns in required_columns.items():

                # Failure Case 2：工作表不存在
                if sheet_name not in wb.sheetnames:
                    return {
                        "status": "error",
                        "message": f"Missing sheet: {sheet_name}"
                    }

                ws = wb[sheet_name]
                rows = ws.iter_rows(values_only=True)
                header_row = next(rows, None)

                if header_row is None:
                    return {
                        "status": "error",
                        "message": f"Empty sheet: {sheet_name}"
                    }

                headers = [
                    str(h).strip() if h is not None else ""
                    for h in header_row
                ]

                # Failure Case 3：必要欄位缺失
                missing = [
                    col for col in columns if col not in headers
                ]

                if missing:
                    return {
                        "status": "error",
                        "message": f"{sheet_name} missing columns: {missing}"
                    }

                data[sheet_name] = []

                for row_number, values in enumerate(rows, start=2):
                    record = {
                        col: (
                            str(values[headers.index(col)]).strip()
                            if values[headers.index(col)] is not None
                            else ""
                        )
                        for col in columns
                    }

                    if any(record.values()):
                        record["_row"] = row_number
                        data[sheet_name].append(record)

            issues = []

            sg_ids = {
                row["ID"] for row in data["SG"] if row["ID"]
            }

            fsr_ids = {
                row["ID"] for row in data["FSR"] if row["ID"]
            }

            referenced_sg = set()
            referenced_fsr = set()

            # 檢查 FSR 是否對應有效 SG
            for fsr in data["FSR"]:
                sg_id = fsr["SG_ID"]

                if sg_id in sg_ids:
                    referenced_sg.add(sg_id)
                else:
                    issues.append({
                        "type": "INVALID_SG_REFERENCE",
                        "requirement": fsr["ID"],
                        "row": fsr["_row"],
                        "message": f"FSR {fsr['ID']} has no valid SG"
                    })

            # 檢查 TSR 是否對應有效 FSR
            for tsr in data["TSR"]:
                fsr_id = tsr["FSR_ID"]

                if fsr_id in fsr_ids:
                    referenced_fsr.add(fsr_id)
                else:
                    issues.append({
                        "type": "INVALID_FSR_REFERENCE",
                        "requirement": tsr["ID"],
                        "row": tsr["_row"],
                        "message": f"TSR {tsr['ID']} has no valid FSR"
                    })

            # 檢查 SG 是否缺少 FSR
            for sg in data["SG"]:
                if sg["ID"] and sg["ID"] not in referenced_sg:
                    issues.append({
                        "type": "SG_WITHOUT_FSR",
                        "requirement": sg["ID"],
                        "row": sg["_row"],
                        "message": f"SG {sg['ID']} has no FSR"
                    })

            # 檢查 FSR 是否缺少 TSR
            for fsr in data["FSR"]:
                if fsr["ID"] and fsr["ID"] not in referenced_fsr:
                    issues.append({
                        "type": "FSR_WITHOUT_TSR",
                        "requirement": fsr["ID"],
                        "row": fsr["_row"],
                        "message": f"FSR {fsr['ID']} has no TSR"
                    })

            return {
                "status": "success",
                "summary": {
                    "SG_count": len(data["SG"]),
                    "FSR_count": len(data["FSR"]),
                    "TSR_count": len(data["TSR"]),
                    "issue_count": len(issues)
                },
                "issues": issues
            }

        finally:
            wb.close()

    except Exception as e:
        return {
            "status": "error",
            "message": f"Excel parsing failed: {str(e)}"
        }
