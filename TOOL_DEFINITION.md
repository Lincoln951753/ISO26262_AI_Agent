# Tool Definition — ISO 26262 Functional Safety Document Review AI Agent

**指定作業二：可執行 Agent + Tool Calling / State-based Decision（MVP）**  
**核心工具：** `traceability_check`  
**文件用途：** 作業二正式繳交之 Tool Definition，與 `agent.py`、`tools/traceability_check.py`、`test_tool.py` 及 `README.md` 相互對應。

> **範圍聲明：** 本工具以專案自訂的模擬 Excel 資料，執行 SG、FSR、TSR **結構化欄位及 ID 追溯關係檢查**。目前**未將 ISO 26262 正式標準文件作為審查依據**，亦未導入標準條款 RAG、需求語義分析或符合性判定。`status=success` 僅表示工具執行成功，不表示資料無缺失或符合 ISO 26262。

## 1. Tool Overview

| 項目 | 說明 |
| --- | --- |
| Tool Name | `traceability_check` |
| Purpose | 對 SG → FSR → TSR 進行結構化 ID 追溯、欄位與資料品質檢查 |
| 核心實作 | `tools/traceability_check.py`：Python、`openpyxl` |
| Agent Binding | `agent.py` 使用 LangChain `@tool("traceability_check")` 包裝 `check_excel(file_path: str)`，內部呼叫 Python 函式 `traceability_check(file_path)` |
| Agent Workflow | Qwen3 Tool Calling + LangGraph StateGraph + Observation 驗證 + State-based Decision |
| 部署方式 | Python Agent 使用 Podman Container；透過 `iso26262-net` 與 Ollama Container 溝通 |

LLM **負責選擇是否提出工具呼叫**，並不直接讀取 Excel；真正的檢查由 Python 工具執行。工具檢查結果以 JSON 作為 Observation，供 LangGraph 決定後續流程。

## 2. Input Definition

**Tool 參數名稱：** `file_path`  
**資料型態：** `string`  
**Agent 呼叫範例：** `{"file_path": "safety_requirements.xlsx"}`

### 2.1 檔案與路徑限制

- 從 Agent 呼叫時，只允許提供 `test_data/` 內的 **`.xlsx` 檔名**，例如 `safety_requirements.xlsx`；不可提供目錄、路徑分隔符或其他副檔名。
- `agent.py` 還會檢查工具呼叫中的 `file_path` 是否與使用者透過 `REVIEW_FILE` 指定的檔名一致，避免模型擅自改換審查檔案。
- 底層 Python 函式另外支援 `test_data/filename.xlsx` 和解析後仍位於專案 `test_data/` 內的絕對路徑；拒絕目錄跳脫及指向目錄外的符號連結。
- 目前這是**專案內預先放置測試檔的執行方式**，**尚不支援使用者上傳檔案**。

### 2.2 專案自訂 Excel Schema

| 工作表 | 必要欄位 | 用途 |
| --- | --- | --- |
| `SG` | `ID`, `Description` | 安全目標 ID 與描述 |
| `FSR` | `ID`, `SG_ID`, `Description` | 功能安全需求 ID、所引用的 SG ID 與描述 |
| `TSR` | `ID`, `FSR_ID`, `Description` | 技術安全需求 ID、所引用的 FSR ID 與描述 |

- 欄位標題位於 **Excel 第 1 列**，需求資料自第 2 列起；輸出 `row` 為實際 Excel 列號。
- 每筆 FSR 僅有一個 `SG_ID` 欄位，每筆 TSR 僅有一個 `FSR_ID` 欄位；**尚未支援多對多需求追溯**。
- 上述欄位名稱與資料格式由本專案自行定義，**不是 ISO 26262 規定的固定 Excel 格式**。

## 3. Processing Logic

工具依序執行：

1. **驗證輸入**：限制副檔名及可存取路徑，確認 Excel 檔案存在。
2. **驗證 Workbook 結構**：檢查 `SG`、`FSR`、`TSR` 工作表、標題列及必要欄位；必要欄位名稱重複也會回報錯誤。
3. **讀取資料**：依照工作表讀取每列，保留實際 Excel 列號；完全空白的資料列會略過。三個工作表完全沒有需求資料時回報錯誤。
4. **檢查資料品質**：偵測需求 ID 重複、需求 ID 空白，以及 `Description` 空白。
5. **檢查引用有效性**：驗證 FSR → SG 與 TSR → FSR 的引用是否存在；若上層 ID 重複，則回報引用歧義。
6. **檢查追溯缺漏**：確認唯一可識別的 SG 是否被 FSR 引用、FSR 是否被 TSR 引用。為避免重複 ID 造成誤判，**「有沒有子需求引用」與「子需求 ID 本身是否有效」分開判斷**。
7. **回傳 Observation**：產生結構化 JSON 結果，由 Agent 進行下一階段狀態決策。

### 3.1 Issue 類型

| Issue Type | 意義 |
| --- | --- |
| `INVALID_SG_REFERENCE` | FSR 沒有填入有效的 SG 引用，或所引用的 SG 不存在 |
| `INVALID_FSR_REFERENCE` | TSR 沒有填入有效的 FSR 引用，或所引用的 FSR 不存在 |
| `AMBIGUOUS_SG_REFERENCE` | FSR 引用了具有重複 ID 的 SG，無法唯一識別上層需求 |
| `AMBIGUOUS_FSR_REFERENCE` | TSR 引用了具有重複 ID 的 FSR，無法唯一識別上層需求 |
| `SG_WITHOUT_FSR` | 唯一可識別的 SG 未被任何 FSR 引用 |
| `FSR_WITHOUT_TSR` | 唯一可識別的 FSR 未被任何 TSR 引用 |
| `DUPLICATE_SG_ID` | SG ID 重複 |
| `DUPLICATE_FSR_ID` | FSR ID 重複 |
| `DUPLICATE_TSR_ID` | TSR ID 重複 |
| `MISSING_ID` | 需求資料列的 `ID` 空白 |
| `MISSING_DESCRIPTION` | 需求資料列的 `Description` 空白 |

> **注意：** 以上 Issue 屬於模擬資料的結構與追溯問題，不是「違反 ISO 26262 條款」的判定。完全空白列會被略過，不視為 `MISSING_ID`。

## 4. Output Definition

### 4.1 成功執行（可能仍包含 Issue）

以 `test_data/safety_requirements.xlsx` 的 TC-01 為例：

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

`summary` 為各工作表的有效資料列筆數與 Issue 數量；`issues` 包含 `type`、`requirement`、`row`、`message`。`issue_count = 0` 表示**沒有發現本工具規則所涵蓋的結構問題**，並不表示符合 ISO 26262。

### 4.2 工具執行失敗

例如 FSR 工作表缺少 `SG_ID` 必要欄位：

```json
{
  "status": "error",
  "message": "FSR missing columns: ['SG_ID']"
}
```

`status=error` 表示**本次工具檢查無法完成**，不可依此產生追溯性完整或不完整的審查結論。

## 5. Error Handling

| 類型 | 發生情境 | 回報與處理 |
| --- | --- | --- |
| Invalid File Path | 非 `.xlsx`、路徑跳脫、非允許位置 | `status=error`，拒絕輸入 |
| File Not Found | 指定檔案不存在 | `status=error`，回報 `File not found` |
| Missing Sheet | 缺少 SG、FSR 或 TSR 工作表 | `status=error`，指出工作表名稱 |
| Empty Sheet | 工作表缺少標題列（完全空白） | `status=error`，回報 `Empty sheet` |
| Missing Required Column | 缺少必要欄位 | `status=error`，指出工作表與缺少欄名 |
| Duplicate Required Column | 必要欄位名稱在標題列重複 | `status=error`，指出重複欄位 |
| No Requirement Data | 三張工作表均沒有需求資料 | `status=error`，不輸出追溯結論 |
| Excel Parsing Error | `.xlsx` 損毀或無法解析 | `status=error`，回報解析異常 |
| Invalid Tool Call | 工具名稱、呼叫次數、參數或檔名不符合 Agent 規則 | Agent 拒絕呼叫並產生 Tool Error Observation |
| Invalid Observation | JSON 無法解析、結果缺欄或資料不一致 | Agent 導向 `error_node`，不產生成功報告 |
| No Tool Call | LLM 未呼叫必要工具 | 最多額外重試一次；仍未呼叫則回報未完成 |
| LLM Service Error | Ollama API 連線失敗或模型異常 | Agent 捕捉異常並輸出固定錯誤訊息 |

**Agent 程序 Exit Code：**

- `0`：Agent 已收到並驗證成功的 Tool Observation；**即使發現 Issue，仍視為程式正常完成檢查**。
- `1`：Tool 檢查失敗、LLM 服務異常、未取得有效 Observation 或其他 Agent 執行錯誤。

`error_node` 的文字由 Python 規則產生，避免 LLM 在沒有可靠檢查結果時虛構需求 ID、Excel 列號或合規結論。

## 6. Agent Workflow

**實際使用的架構是 Tool Calling + State-based Decision，而不是完整 ReAct 或多工具自主 Planning。**

```text
User Input（REVIEW_FILE 指定 Excel）
  ↓
agent_node：Qwen3 判斷並提出 traceability_check Tool Call
  ├─ 無 Tool Call → retry_node（最多再試一次）→ 仍未呼叫則 no_tool_node
  └─ LLM Service Error → error_node
  ↓
tool_node：核對 Tool 名稱、參數、指定檔名，執行 Python Tool
  ↓
Observation：ToolMessage（JSON）
  ↓
decision_node：檢查 status 與 Observation 結構
  ├─ success 且結果有效 → finalize_node（依 Observation 產生固定格式結果）
  └─ error / 不合法 Observation → error_node（固定錯誤回覆）
  ↓
Final Answer / Exit Code
```

**Final Answer 產生方式：** LLM 負責起始的 Tool Calling 決策，Python Tool 負責 Excel 檢查；`decision_node` 驗證 Observation 後，由 `finalize_node` 依有效工具結果組成最終回答，不由 LLM 自行推測問題內容。TC-01 提供完整的 `User Input → Agent Decision → Tool Call → Observation → Agent Decision → Final Answer` 實測紀錄。

## 7. Testing & Evidence

### 7.1 Agent 端到端測試（Windows + WSL2 + Podman + Ollama）

| ID | 測試情境 | 預期結果 | 實際紀錄 |
| --- | --- | --- | --- |
| `TC-01` | 模擬 Excel 中 `FSR-002` 無對應 TSR | Observation `success`、Issue 為 `FSR_WITHOUT_TSR`、第 3 列、Exit Code `0` | **PASS**：`logs/tc01_trace.txt` |
| `FC-01` | Excel 檔案不存在 | `File not found`、走 `error_node`、Exit Code `1` | **PASS**：`logs/fc01_trace.txt` |
| `FC-02` | FSR 工作表缺少 `SG_ID` 欄位 | `FSR missing columns: ['SG_ID']`、Exit Code `1` | **PASS**：`logs/fc02_trace.txt` |
| `FC-03` | Ollama 使用無效 Port（`19999`） | `ConnectError`、明確回報服務失敗、Exit Code `1` | **PASS**：`logs/fc03_trace.txt` |

`FC-03` 在 LLM 呼叫階段就失敗，因此不會產生 Tool Call / Observation；完整 Tool Calling Trace 以 `TC-01` 為準。

### 7.2 Python Tool 單元測試（17 組）

`test_tool.py` 使用 `unittest` 與暫存 Excel，覆蓋：正確追溯、FSR/SG 缺漏、無效引用、重複 ID、引用歧義、空白欄位、空白資料列、無需求資料、缺工作表、缺必要欄位、重複表頭、檔案不存在、非法路徑、錯誤副檔名、損毀 Excel。

在專案根目錄完成 Podman Build 後執行：

```powershell
podman build -t iso26262-agent:dev -f Containerfile .
podman run --rm --entrypoint python iso26262-agent:dev test_tool.py
Write-Host "Exit Code: $LASTEXITCODE"
```

**已提供的實測結果：** `Ran 17 tests`、`OK`、`Exit Code: 0`；保存於 `logs/tool_unittest_trace.txt`。

上述 17 組為**Python Tool 單元測試**，**不是 17 組含 LLM 的端到端 Agent 測試**。另曾手動在臨時容器驗證重複 FSR、空白欄位、無效引用與完全正確追溯關係；正式可重複測試則以 `test_tool.py` 為準。

### 7.3 尚待驗證項目

- 從 GitHub `main` **全新 Clone → Podman Build → Run → Test**，確認公開 Repository 可獨立重現；目前尚無本次提交版本的完整重現測試紀錄。
- 在其他作業系統／獨立 Podman 平台進行重現驗證；目前只確認 Windows + WSL2 + Podman。
- 「LLM 連續未呼叫 Tool」、「不合法 Observation」等 Agent 邊界分支，尚未提供獨立端到端實測證據。

## 8. Limitations & Future Work

- 只支援**專案自訂 `.xlsx` 格式**與 SG／FSR／TSR 的結構化欄位、單一上層 ID 追溯。
- 目前未使用 ISO 26262 正式標準條文作為檢索或審查依據，**尚無 RAG**；也不會聲稱通過 ISO 26262 合規或認證。
- 尚未解析 HARA／FSC／TSC PDF、檢查需求語義一致性、ASIL 分配合理性、設計／驗證證據或產生正式 Gap Analysis Report。
- 本次作業聚焦可執行 Agent、真實 Tool、Error Handling、完整 Trace 與容器測試；上述進階能力列為後續開發方向。

參考：專案 [`README.md`](README.md)、[`agent.py`](agent.py)、[`tools/traceability_check.py`](tools/traceability_check.py)、[`test_tool.py`](test_tool.py) 與 `logs/`。正式繳交前，應確保文件中的「已測試」描述與提交的程式碼及測試證據屬於同一版本。
