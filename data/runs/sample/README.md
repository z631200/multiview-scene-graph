# 可追蹤的實驗範例

- exp_20261021T162018_966707Z/：歷史 VLM 回答、提示、原始 manifest 與可追溯 JSON 匯出。
  原始拍攝資料不在專案內，場景為 unidentified_scene，不能推測為目前 FloorPlan1 的 GT 評分資料。
- demo_legacy/：舊固定任務的 trace_log.json、run.mp4 與當時的環境紀錄。

兩個範例都有 config.yaml、run_manifest.json、summary.csv 索引。
summary 只標示 historical，沒有建立不存在的評分。
原始推理紀錄保存在 legacy/，方便核對；它不是可直接 resume 的新格式模型實驗。

這個 sample/ 由 Git 追蹤；新實驗預設放在 data/runs/exp_<UTC>/，由 Git 忽略。
