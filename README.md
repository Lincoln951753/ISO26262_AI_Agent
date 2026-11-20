# ISO 26262 Functional Safety Document Review AI Agent

## 1. Project Overview

本專案為「基於 LLM 決策、RAG 與工具調用之 ISO 26262 功能安全文件審查 AI Agent」的第二階段實作。

目標是建立一個以大型語言模型（LLM）為決策核心，結合 LangGraph 與 Python Tools 的 AI Agent，協助功能安全工程師對 SG（Safety Goal）、FSR（Functional Safety Requirement）及 TSR（Technical Safety Requirement）進行初步文件追溯性檢查。

目前版本為第二次作業的最小可執行雛形（MVP），主要驗證：

- LLM 自主選擇與呼叫工具（Tool Calling）。
- Python Tool 實際執行 Excel 資料檢查。
- Agent 接收工具結果（Observation）並決定後續流程。
- 工具執行失敗時進行錯誤處理（Error Handling）。
- 透過 Podman Engine 部署及執行 Agent。

**目前使用自行建立的模擬 Excel 資料，尚未實作 ISO 26262 正式條款檢索（RAG），不提供標準符合性認定。**

## 2. System Architecture

本專案使用兩個 Podman 容器：

**Container 1：Ollama LLM Server**

- Ollama Server
- Qwen3 4B Instruct
- 提供 HTTP API

**Container 2：Python Agent**

- Python 3.12
- LangGraph
- LangChain / ChatOllama
- openpyxl
- Traceability Check Tool

執行流程：

```text
User Input
    |
    v
LangGraph Agent
    |
    v
Qwen3 LLM
    |
    v
Tool Calling Decision
    |
    v
traceability_check
    |
    v
Excel Parsing & Traceability Check
    |
    v
Tool Observation
    |
    v
LangGraph Conditional Routing
    |
    +---- Success ---> LLM Analysis ---> Final Answer
    |
    +---- Error -----> Error Node -----> Error Report
```

兩個容器透過 Podman 網路 `iso26262-net` 進行 HTTP 通訊。

## 3. Development Environment

本次開發及驗證環境：

| Item | Environment |
|---|---|
| Host OS | Windows 11 x64 |
| Container Engine | Podman 6.1.4 |
| Virtualization | WSL2 |
| LLM Server | Ollama 0.40.16 |
| LLM Model | qwen3:4b-instruct |
| Agent Framework | LangGraph |
| Programming Language | Python 3.12 |
| Excel Library | openpyxl 3.1.5 |
| Development IDE | Visual Studio Code |

LLM 目前以容器內 CPU 模式執行，尚未驗證 NVIDIA GPU passthrough。

## 4. Project Structure

```text
ISO26262_AI_Agent/
├── agent.py
├── Containerfile
├── requirements.txt
├── TOOL_DEFINITION.md
├── README.md
├── test_tool.py
├── tools/
│   └── traceability_check.py
├── test_data/
│   ├── safety_requirements.xlsx
│   └── fc02_missing_column.xlsx
└── logs/
    ├── tc01_trace.txt
    ├── fc01_trace.txt
    └── fc02_trace.txt
```

主要檔案說明：

| File | Description |
|---|---|
| agent.py | LangGraph Agent 主要程式 |
| traceability_check.py | Excel 追溯性檢查工具 |
| requirements.txt | Python 相依套件 |
| Containerfile | Podman Agent 容器建置設定 |
| TOOL_DEFINITION.md | Tool 輸入、輸出及錯誤處理定義 |
| test_data/ | 模擬功能安全需求測試資料 |
| logs/ | Agent 執行追蹤紀錄 |

## 5. Installation and Deployment

以下指令以 Windows PowerShell 為例。

### 5.1 Prerequisites

請先安裝：

- WSL2
- Podman CLI / Podman Desktop
- Git（下載 GitHub 專案時使用）

Podman Machine 必須使用 WSL2 並處於執行狀態。

確認 Podman 版本：

```powershell
podman --version
```

確認 Machine：

```powershell
podman machine list
```

如果 Machine 已建立但未執行，可使用：

```powershell
podman machine start
```

若尚未建立 Machine，請先使用 Podman Desktop 建立 WSL2 Podman Machine。

### 5.2 Create Podman Network

建立 Ollama 與 Python Agent 之間的專用網路：

```powershell
podman network create iso26262-net
```

若網路已經存在，不需重複建立。

### 5.3 Start Ollama Container

首次部署時執行：

```powershell
podman run -d --name ollama --network iso26262-net -p 127.0.0.1:11434:11434 -v ollama:/root/.ollama docker.io/ollama/ollama:latest
```

若既有 Ollama 容器已建立，只需確認已連接 `iso26262-net`，並在停止時執行：

```powershell
podman start ollama
```

下載本機 LLM：

```powershell
podman exec ollama ollama pull qwen3:4b-instruct
```

確認模型：

```powershell
podman exec ollama ollama list
```

確認容器狀態：

```powershell
podman ps
```

### 5.4 Verify Ollama API

在 Windows PowerShell 執行：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/version
```

成功時會回傳 Ollama 版本資訊。

### 5.5 Build Agent Image

在包含 `Containerfile` 的專案根目錄執行：

```powershell
podman build -t iso26262-agent:dev -f Containerfile .
```

此指令會建立包含 Python、LangGraph、依賴套件與測試資料的 Agent 映像。

### 5.6 Run Agent

執行正常測試：

```powershell
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=safety_requirements.xlsx iso26262-agent:dev
```

正常執行流程包含：

1. User Input
2. Agent Action / Tool Calling
3. Tool Observation
4. Final Answer

本專案測試版本的 `REVIEW_FILE` 用來指定 `test_data` 內的 Excel 檔名。

## 6. Tool Description

本階段主要工具為：

**Tool Name：** `traceability_check`

**Input：** Excel filename (`file_path`)

**Output：** JSON

主要功能：

- 檢查 Excel 檔案是否存在。
- 驗證 SG、FSR、TSR 工作表與必要欄位。
- 檢查 FSR 與 SG 之間的 ID 關聯。
- 檢查 TSR 與 FSR 之間的 ID 關聯。
- 找出沒有對應 FSR 的 SG。
- 找出沒有對應 TSR 的 FSR。
- 回傳檢查問題及相關 Excel 行號。

詳細 Tool 定義請參考 `TOOL_DEFINITION.md`。

## 7. Test Cases

本階段已執行三項測試。

| Test ID | Test Scenario | Expected Result | Status |
|---|---|---|---|
| TC-01 | 正常格式 Excel，包含一筆缺少 TSR 的 FSR | 找出 FSR-002 缺少 TSR | PASS |
| FC-01 | Excel 檔案不存在 | 回報 File Not Found | PASS |
| FC-02 | FSR 工作表缺少 SG_ID | 回報 Missing Required Column | PASS |

### 7.1 TC-01：Normal Traceability Check

```powershell
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=safety_requirements.xlsx iso26262-agent:dev
```

預期偵測：

- Requirement ID：FSR-002
- Issue Type：FSR_WITHOUT_TSR
- Excel Row：3

### 7.2 FC-01：File Not Found

```powershell
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=not_found.xlsx iso26262-agent:dev
```

預期 Observation：

```json
{
  "status": "error",
  "message": "File not found: /app/test_data/not_found.xlsx"
}
```

Agent 應回報檔案不存在，不得編造審查結果。

### 7.3 FC-02：Missing Required Column

```powershell
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=fc02_missing_column.xlsx iso26262-agent:dev
```

預期 Observation：

```json
{
  "status": "error",
  "message": "FSR missing columns: ['SG_ID']"
}
```

Agent 應指出輸入資料格式錯誤，停止追溯性分析。

## 8. Agent Execution Trace

本專案透過 LangGraph Streaming 輸出執行追蹤資訊，包括：

- User Input
- Agent Action
- Tool Calling Parameters
- Observation
- Final Answer

已保存的測試證據：

```text
logs/tc01_trace.txt
logs/fc01_trace.txt
logs/fc02_trace.txt
```

這些紀錄用來展示 Agent 的執行流程及錯誤處理行為。

## 9. Error Handling

當 Tool 回傳錯誤時，LangGraph 會依據 Observation 的 `status` 進行條件分流。

- `status = success`：將結果交回 LLM 分析。
- `status = error`：進入 Error Node，由 Python 組成固定格式的錯誤訊息。

這可降低 LLM 在錯誤處理時自行產生不存在的 Excel 行號、欄位或安全需求判斷的風險。

## 10. Limitations

目前系統為第二次作業之 Agent MVP，存在以下限制：

1. 目前僅支援指定格式的 Excel。
2. 測試資料為自行建立的模擬功能安全需求。
3. 尚未實作正式 ISO 26262 條款 RAG 檢索。
4. 尚未支援 PDF 文件解析。
5. 尚未進行安全需求語義一致性分析。
6. 尚未完整支援自動補查與多工具重新規劃。
7. 不提供正式 ISO 26262 符合性認定。
8. 容器執行環境已在 Windows + WSL2 驗證，尚未完成其他平台測試。

## 11. Future Work

後續開發方向：

**第三次作業：Agent 功能強化與實驗**

- 建立可合法使用的功能安全知識來源。
- 導入 RAG 或更完整的審查機制。
- 增加至少 10 個測試案例。
- 比較強化前後之審查效果。

**期末作業：完整 Agent 系統**

- HARA／FSC／TSC 文件解析。
- ISO 26262 標準知識檢索。
- 安全需求一致性及證據檢查。
- Gap Analysis Report。
- 審查紀錄保存與 Web UI。
- 完整的 Agent 測試與技術文件。

## 12. Disclaimer

本專案目前為 AI Agent 技術概念驗證及教學用途。

目前檢查結果僅反映模擬 Excel 文件中的結構化追溯性狀態，不能用於認定實際車輛系統是否符合 ISO 26262。

所有功能安全審查結論均須由具備相關專業知識的工程人員複核。