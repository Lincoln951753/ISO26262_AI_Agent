import json
from tools.traceability_check import traceability_check

# 執行 ISO 26262 安全需求追溯性檢查
result = traceability_check(
    "test_data/safety_requirements.xlsx"
)

# 顯示檢查結果
print(json.dumps(result, indent=2, ensure_ascii=False))
