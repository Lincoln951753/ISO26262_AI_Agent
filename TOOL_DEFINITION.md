# Tool Definition — ISO 26262 AI Agent

## 1. Tool Overview

- **Tool Name:** `traceability_check`
- **Implementation:** Python + openpyxl
- **Framework:** LangGraph + LangChain Tool
- **Purpose:** 檢查 Excel 中 SG（Safety Goal）、FSR（Functional Safety Requirement）與 TSR（Technical Safety Requirement）的結構化追溯關係。

本工具為 AI Agent 第二次作業的 MVP 功能，主要驗證 Tool Calling 與功能安全需求追溯性檢查的技術可行性。

目前使用模擬測試資料，尚未整合 ISO 26262 正式條款 RAG 知識庫，因此不進行正式標準符合性判定。

## 2. Input

**參數：** `file_path`

**資料型態：** `string`

**範例：**
`"safety_requirements.xlsx"`

工具僅允許讀取 `/app/test_data/` 目錄中的 `.xlsx` 檔案。

Excel 格式：

| 工作表 | 必要欄位 |
|---|---|
| SG | ID, Description |
| FSR | ID, SG_ID, Description |
| TSR | ID, FSR_ID, Description |

以上欄位名稱由本專案自訂，並非 ISO 26262 規定的固定欄位名稱。

## 3. Processing Logic

工具執行以下檢查：

1. 確認 Excel 檔案存在。
2. 確認 SG、FSR、TSR 工作表存在。
3. 確認工作表包含必要欄位。
4. 檢查 FSR 所引用的 SG ID 是否存在。
5. 檢查 TSR 所引用的 FSR ID 是否存在。
6. 檢查 SG 是否具有 FSR 關聯。
7. 檢查 FSR 是否具有 TSR 關聯。
8. 回傳結構化 JSON 結果。

## 4. Output

**成功時：**

```json
{
  "status": "success",
  "summary": {
    "SG_count": 2,
    "FSR_count": 2,
    "TSR_count": 1,
    "issue_count": 1
  },
  "issues": [
    {
      "type": "FSR_WITHOUT_TSR",
      "requirement": "FSR-002",
      "row": 3,
      "message": "FSR FSR-002 has no TSR"
    }
  ]
}
```

**失敗時：**

```json
{
  "status": "error",
  "message": "FSR missing columns: ['SG_ID']"
}
```

## 5. Error Handling

| 錯誤類型 | 處理方式 |
|---|---|
| File Not Found | 回傳檔案不存在錯誤 |
| Missing Sheet | 回傳缺少的工作表名稱 |
| Missing Column | 回傳缺少的必要欄位 |
| Empty Sheet | 回傳工作表為空的錯誤 |
| Invalid File Path | 拒絕不符合檔名限制的輸入 |
| Excel Parsing Error | 回傳解析失敗訊息 |

當工具回傳 `status = error` 時，LangGraph 進入 `error_node`，由 Python 根據工具輸出產生錯誤訊息，避免 LLM 自行編造審查結果。

## 6. Agent Workflow

1. 使用者提出 Excel 追溯性檢查需求。
2. Qwen3 LLM 決定呼叫 `traceability_check`。
3. LangGraph Tool Node 執行 Python 工具。
4. Python Tool 回傳 JSON Observation。
5. LangGraph 根據 `status` 進行條件式分流。
6. 成功時由 LLM 分析結果；失敗時由 Error Node 回報問題並結束。

## 7. Test Cases

| Test ID | Scenario | Expected Result | Status |
|---|---|---|---|
| TC-01 | 正常格式 Excel，包含一筆缺少 TSR 的 FSR | 偵測 FSR-002 缺少 TSR | PASS |
| FC-01 | Excel 檔案不存在 | 回傳 File Not Found | PASS |
| FC-02 | FSR 缺少 SG_ID 欄位 | 回傳 Missing Column | PASS |

測試紀錄分別儲存於：

- `logs/tc01_trace.txt`
- `logs/fc01_trace.txt`
- `logs/fc02_trace.txt`

## 8. Limitations

目前工具僅支援指定格式的 Excel 結構化追溯性檢查。

尚未完成：

- ISO 26262 正式條款 RAG 檢索
- PDF 文件解析
- 安全需求語義一致性分析
- ASIL 合理性評估
- 正式功能安全符合性判定

以上功能預計於後續作業逐步強化。