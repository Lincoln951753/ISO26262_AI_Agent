# ISO 26262 Functional Safety Document Review AI Agent

> **指定作業二｜可執行 Agent + Tool / State-based Decision（MVP）**  
> 技術：Python · LangGraph · Qwen3 4B Instruct · Ollama · Podman · openpyxl

## 1. 專案概述

本專案延續第一次作業「基於 LLM 決策、RAG 與工具調用之 ISO 26262 功能安全文件審查 AI Agent」的規劃。本階段的目標不是完成正式的 ISO 26262 合規審查，而是將設計轉換成**可透過 Podman 執行與測試的 AI Agent 最小可行雛形（MVP）**。

目前使用自行建立的模擬 Excel，示範檢查下列需求之間的**結構化 ID 追溯關係**：

- **SG**：Safety Goal（安全目標）
- **FSR**：Functional Safety Requirement（功能安全需求）
- **TSR**：Technical Safety Requirement（技術安全需求）

Agent 能透過 LLM 選擇 Python Tool、接收工具執行結果（Observation），並依結果回到 LLM 分析或進入固定的錯誤處理流程。

**重要限制：本階段使用模擬測試資料，尚未導入 ISO 26262 標準原文、正式條款檢索（RAG）或真實工程文件；輸出不能視為 ISO 26262 符合性結論。**

## 2. 實作成果與範圍

| 功能 | 本階段狀態 |
| --- | --- |
| 本機 LLM 推論（Ollama + Qwen3） | 已實作與測試 |
| LLM 選擇 `traceability_check`（Tool Calling） | 已實作與測試 |
| 讀取指定 Excel 工作表並驗證 ID 關聯 | 已實作與測試 |
| Tool Observation 回傳及 LangGraph 條件分流 | 已實作與測試 |
| 錯誤時由 Python `error_node` 產生結果 | 已實作與測試 |
| Podman 執行 Ollama 與 Python Agent | 已在 Windows + WSL2 測試 |
| ISO 26262 正式條款 RAG / PDF 解析 | 尚未實作 |
| 真實 HARA / FSC / TSC 文件審查 | 尚未驗證 |
| 跨平台與乾淨環境完整重現測試 | 尚待驗證 |

本專案採用 **Tool Calling + State-based Decision**，而不是宣稱已實作完整的 ReAct 或多步規劃系統。LangGraph 負責控制狀態與路由，LLM 負責工具選擇及成功案例的文字分析。

## 3. 系統架構與決策流程

```text
Windows 11 + WSL2
       |
       v
   Podman Engine
       |
       +-- Ollama Container (qwen3:4b-instruct)
       |        ^
       |        | HTTP: http://ollama:11434
       |        v
       +-- Python Agent Container (LangGraph)
                    |
User Input --------> agent_node (LLM Decision)
                    |
                    | Tool Call: traceability_check(file_path)
                    v
                 tool_node
                    |
                    v
             Excel / Python Tool
                    |
                    v
           Tool Observation (JSON)
                    |
                    v
           route_after_tools
              /           \
       status=success   status=error
            |               |
            v               v
       agent_node        error_node
       LLM analysis      fixed error report
            |               |
            +------> Final Answer
```

主要節點與責任：

| 程式元件 | 責任 |
| --- | --- |
| `agent_node()` | 將對話狀態送交 Qwen3，取得下一個決策或回答 |
| `tool_node()` | 依 Tool Call 名稱與參數實際執行 Python 工具，回傳 `ToolMessage` |
| `route_after_agent()` | 判斷模型是否要求呼叫工具 |
| `route_after_tools()` | 根據 JSON 中的 `status` 導向正常分析或錯誤處理 |
| `error_node()` | 不再讓 LLM 自由補寫錯誤內容，改由 Python 組成固定錯誤報告 |

**Tool Calling 的意義：** LLM 只產生工具名稱與參數；真正讀取 Excel、驗證欄位及 ID 關聯的是 Python 程式。Agent 再根據 Observation 決定下一步。

## 4. 開發與驗證環境

| 項目 | 已使用的環境 |
| --- | --- |
| 主機作業系統 | Windows 11 x64 |
| 編輯器 | Visual Studio Code |
| Linux 容器執行環境 | WSL2 + Podman Machine |
| Podman CLI | 6.1.4 |
| Ollama API | 0.40.16（開發時檢查結果） |
| LLM 模型 | `qwen3:4b-instruct` |
| Python | 3.12（容器） |
| Agent Framework | LangGraph / LangChain |
| Excel 套件 | openpyxl 3.1.5 |

目前未驗證 NVIDIA GPU passthrough，測試以不要求 GPU 加速的方式進行。`requirements.txt` 中部分套件採版本範圍、Ollama 映像使用 `latest`，因此**尚未做到依賴版本完全固定**；這是後續部署重現的改善項目。

## 5. 專案目錄

```text
ISO26262_AI_Agent/
├── agent.py                    # LangGraph Agent 主程式
├── Containerfile               # Python Agent 容器建置
├── requirements.txt            # Python 依賴
├── test_tool.py                # 獨立 Python Tool 測試
├── TOOL_DEFINITION.md          # Tool 規格及錯誤處理
├── README.md
├── tools/
│   └── traceability_check.py   # Excel 追溯關係檢查
├── test_data/
│   ├── safety_requirements.xlsx
│   └── fc02_missing_column.xlsx
└── logs/
    ├── tc01_trace.txt
    ├── fc01_trace.txt
    └── fc02_trace.txt
```

`test_data/` 是**模擬測試資料**，`logs/` 是當次測試保存的 Agent 執行紀錄；本儲存庫不包含 ISO 26262 標準全文或車廠機敏文件。

## 6. 安裝、建置與執行（Windows PowerShell）

以下為第二次作業 MVP 的部署程序。此流程已在開發者的 Windows + WSL2 環境中分階段測試，但尚未在另一台乾淨主機上完整重跑。

### 6.1 必要條件與取得專案

請先安裝 **Git、WSL2 與 Podman CLI / Podman Desktop**，並透過 Podman Desktop 建立 **WSL2 Podman Machine**。確認：

```powershell
podman --version
podman machine list
```

如果 Machine 已建立但未啟動：

```powershell
podman machine start
```

複製 GitHub 專案：

```powershell
git clone https://github.com/Lincoln951753/ISO26262_AI_Agent.git
cd ISO26262_AI_Agent
```

### 6.2 建立容器網路

第一次部署時：

```powershell
podman network create iso26262-net
```

如果已存在同名網路，則不必重複建立。

### 6.3 啟動 Ollama Server

**第一次部署、尚未建立 `ollama` 容器時：**

```powershell
podman run -d --name ollama --network iso26262-net -p 127.0.0.1:11434:11434 -v ollama:/root/.ollama docker.io/ollama/ollama:latest
```

**如果既有 Ollama 容器已建立：** 先使用 `podman ps -a` 確認狀態；若尚未連接網路，可執行 `podman network connect iso26262-net ollama`（已連線則不用重複）；若容器已停止，可執行 `podman start ollama`。

下載模型並確認：

```powershell
podman exec ollama ollama pull qwen3:4b-instruct
podman exec ollama ollama list
podman ps
```

驗證 Windows 到 Ollama API：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/version
```

若要確認**另一個 Podman 容器**能以主機名稱 `ollama` 連線：

```powershell
podman run --rm --network iso26262-net docker.io/library/python:3.12-slim python -c "import urllib.request; print(urllib.request.urlopen('http://ollama:11434/api/version').read().decode())"
```

### 6.4 Build Python Agent

在專案根目錄執行：

```powershell
podman build -t iso26262-agent:dev -f Containerfile .
```

此 `Containerfile` 將 `agent.py`、`tools/`、`test_data/` 複製進 Agent 映像。**修改 Python 程式或測試 Excel 後需要重新 Build**，新的內容才會進入容器。

### 6.5 執行 Agent

```powershell
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=safety_requirements.xlsx iso26262-agent:dev
```

`REVIEW_FILE` 指定 `/app/test_data/` 目錄中的 Excel 檔名。正常輸出可看到 `User Input`、`Agent Action`、`Observation`、`Final Answer`。本階段的問句由 `agent.py` 依環境變數產生，尚未提供 Web UI 或任意文件上傳介面。

## 7. Traceability Check Tool 定義

- **Tool 名稱**：`traceability_check`
- **目的**：檢查 SG → FSR → TSR 的結構化 ID 追溯關係
- **輸入**：`file_path`（僅允許 `test_data` 內的 `.xlsx` 檔名）
- **輸出**：JSON（`status`、`summary`、`issues` 或 `message`）
- **錯誤處理**：檔案不存在、工作表／欄位缺漏、空白工作表、無效路徑、Excel 解析失敗等

測試 Excel 格式：

| 工作表 | 必要欄位 |
| --- | --- |
| `SG` | `ID`, `Description` |
| `FSR` | `ID`, `SG_ID`, `Description` |
| `TSR` | `ID`, `FSR_ID`, `Description` |

**這些欄位名稱是本專案解析器的資料格式，不是 ISO 26262 官方規定的固定欄位名稱。**

工具會檢查 FSR 引用的 SG、TSR 引用的 FSR 是否存在，並找出沒有建立下層關聯的 SG 或 FSR。更多輸入、輸出與錯誤範例請參考 [TOOL_DEFINITION.md](TOOL_DEFINITION.md)。

## 8. 實際測試與執行證據

本階段已在 Podman 容器中執行以下三種案例：

| ID | 測試資料與情境 | 實際觀察結果 | 結果 |
| --- | --- | --- | --- |
| TC-01 | `safety_requirements.xlsx`（格式正常，刻意設定一筆追溯缺漏） | `FSR-002` 缺少 TSR，Excel 第 3 列 | PASS（結構檢查） |
| FC-01 | `not_found.xlsx`（故意不存在） | `File not found: /app/test_data/not_found.xlsx` | PASS |
| FC-02 | `fc02_missing_column.xlsx`（FSR 缺 `SG_ID`） | `FSR missing columns: ['SG_ID']` | PASS |

依序重現三項測試（每次執行一個指令）：

```powershell
# TC-01 正常格式但有一筆關聯缺漏
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=safety_requirements.xlsx iso26262-agent:dev

# FC-01 檔案不存在
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=not_found.xlsx iso26262-agent:dev

# FC-02 必要欄位缺失
podman run --rm --network iso26262-net -e OLLAMA_BASE_URL=http://ollama:11434 -e REVIEW_FILE=fc02_missing_column.xlsx iso26262-agent:dev
```

已保存執行追蹤：

- [TC-01 Trace](logs/tc01_trace.txt)
- [FC-01 Trace](logs/fc01_trace.txt)
- [FC-02 Trace](logs/fc02_trace.txt)

Trace 展示 `User Input → Agent Action / Tool Call → Observation → Agent Decision → Final Answer` 的流程。當 Tool 的 `status=error` 時，LangGraph 進入 `error_node`，由程式回報錯誤、不讓 LLM 自行補寫欄位或行號。正常路徑的最終敘述仍由 LLM 生成，仍需人工檢查措辭與證據是否一致。

## 9. 開發過程：AI 輔助、實際參與與驗證

### 9.1 AI 輔助的範圍

本專案使用 **ChatGPT 作為開發與學習輔助工具**，包括：討論系統架構與技術選擇、提供 Podman / Ollama / LangGraph 設定指引、產生初版 Python Agent 與 Tool 程式碼、協助分析錯誤訊息、提出測試案例及整理 README / Tool 定義等文件。

**AI 協助生成的內容不直接等於已驗證成果。** 只有在實際執行、比對預期與觀察結果後，才將相應功能記錄為已測試。本文件也不將 AI 生成的初版程式碼描述為學生完全獨立撰寫。

### 9.2 實際操作與確認的工作

| 實作階段 | 親自執行與確認的工作 |
| --- | --- |
| 執行環境 | 安裝 WSL2、Podman Desktop / CLI，建立並啟動 Podman Machine |
| 容器驗證 | 執行 `hello-world`，確認 Podman 確實能啟動 Linux 容器 |
| 本地 LLM | 建立 Ollama 容器、下載 Qwen3、測試 `/api/version` 與模型問答 |
| Tool Calling | 實際呼叫 Ollama API，確認模型產生 `traceability_check` 工具名稱與參數 |
| Python Tool | 在 VS Code 建立程式與模擬 Excel，使用 Podman 執行並確認輸出 |
| Agent Workflow | 建置 LangGraph Agent，觀察 Action、Observation 與最終回答 |
| 測試與修正 | 執行 TC-01、FC-01、FC-02，依結果修正程式及重新 Build |
| 作業證據 | 保存 Trace、編寫專案說明與 Tool 文件、建立 Git 版本及 GitHub Repository |

### 9.3 遇到的問題與解決方式

| 問題 | 分析與採用的修正方式 | 驗證結果 |
| --- | --- | --- |
| PowerShell 顯示 `host directory cannot be empty` | 修正資料夾掛載路徑，由 `${PWD.Path}` 改成 `$($PWD.Path)` | Python 容器可讀取測試 Excel |
| Python `IndentationError` | 統一 `agent.py` 程式區塊的空格縮排，透過 `ast.parse()` 先檢查語法 | 出現 `Syntax OK`，後續容器可執行 |
| 指定 `REVIEW_FILE` 仍讀到舊檔名 | 檢查 `agent.py` 是否讀取環境變數，修改、儲存並重新 Build | FC-01 正確呼叫 `not_found.xlsx` |
| `Tee-Object` 保存 Trace 出現中文亂碼 | 改用 CMD 重導向文字輸出，重新產生 UTF-8 Trace | 中文可正確開啟與閱讀 |
| LLM 遇到缺欄位時編造行號／欄位 | 先補強 Prompt，後改成 LangGraph `error_node` 固定處理 `status=error` | FC-02 正確指出 `SG_ID` 缺漏，無額外虛構欄位 |

以上紀錄是**實際發生的開發與驗證過程**，不表示所有程式碼都是自行從零撰寫，也不表示已完成所有預定功能。

### 9.4 技術理解與可說明的設計理由

- **為何不是純 LLM 問答？** 因為模型可能誤解 SG / FSR / TSR。讓 Python 工具處理可明確規則化的資料檢查，比直接相信模型更容易驗證。
- **為何使用 LangGraph？** 透過節點、狀態與條件邊，清楚控制 Tool 成功或失敗後的不同執行路徑。
- **Tool Calling 是否等於 LLM 執行程式？** 不是。LLM 只提出函式名稱與參數，真正的執行由 Python Tool Node 完成。
- **為何增加 Error Node？** 在 FC-02 中，僅修改提示詞仍無法完全避免推測內容，所以改由程式根據 Observation 組出可驗證的錯誤回覆。
- **為何使用 Podman？** 符合課程的容器執行要求，並將 Agent 所需的 Python 依賴封裝在映像內。

以上內容作為口頭說明與進一步複習的重點；仍應以能親自解釋程式與重現執行結果為準。

## 10. 目前限制與後續規劃

- 只支援此專案定義的 Excel 欄位及 ID 關聯檢查；**不檢查需求內容的語義正確性**。
- 測試資料為模擬案例，不能代表真實車廠 HARA / FSC / TSC 文件的品質。
- 尚無授權可用的 ISO 26262 完整標準資料、條款 RAG 檢索、引用頁碼及正式 Gap Report。
- 成功路徑的 LLM 回答仍可能使用過度肯定的措辭，應由工程人員複核。
- 尚未完成跨平台測試、完全鎖版的容器依賴、完整自動化測試與 GPU 設定。

**後續作業方向：** 建立合法使用的標準／參考資料來源，加入 RAG、文件解析及證據檢查；擴充至少 10 個測試案例，比較強化前後效果；逐步形成可產出 Gap Analysis Report 的完整系統。

## 11. 使用聲明

本專案為 AI Agent 教學及可行性驗證用途。所有 ISO 26262 相關專業內容均須依可驗證的資料與專業判斷複核；本階段輸出**不構成 ISO 26262 符合性認定**。不得在公開 Repository 上傳受保護的標準原文、真實車廠機敏資料或憑證。
