# 架構與遷移

程式與產生資料分開，所有命令從專案根目錄以 `python3 -m` 執行。

## 程式模組

| 目錄 | 功能 |
| --- | --- |
| configs/ | YAML 設定模板；CLI 明確提供的參數優先 |
| scene_capture/colab/ | 可獨立執行的 Colab Notebook |
| scene_capture/local/ | AI2-THOR 本機拍攝與匯出 |
| scene_capture/demo/ | 固定動作任務、動作介面、目標裁判 |
| reasoning/visible/ | 局部觀察的驗證與忠實 JSON 匯出 |
| reasoning/full/methods/ | 方法模組；目前僅 central_llm，未實作其他合併方法 |
| reasoning/pipeline.py | 保留階段 1–3、重試、resume、fork、來源驗證 |
| reasoning/prompts.py、validation.py、ollama_client.py | 提示、驗證、模型通訊 |
| gt/visible/、gt/full/、gt/common.py | GT 計算與共用產生器 |
| visualization/ | 共用 GT HTML 檢查器 |
| common/ | YAML 讀取、設定快照、路徑與 capture 身分 |
| evaluate/ | 評估介面預留，不產生虛構評分 |

## 資料位置

```text
data/
├── scenes/
│   ├── sample/<scene>/<capture_id>/     Git 追蹤的範例
│   │   ├── basic/                      原始 RGB、metadata、mask、depth
│   │   └── gt/<gt_id>/
│   │       ├── visible/                graphs、measurements、設定、HTML 等
│   │       └── full/                   相同檔案結構
│   └── <scene>/<capture_id>/            一般資料，Git 忽略
└── runs/
    ├── sample/<exp_id>/                 Git 追蹤的歷史範例
    └── <exp_id>/                        一般實驗，Git 忽略
        ├── config.yaml
        ├── run_manifest.json            各場景的索引與狀態
        ├── summary.csv                  場景／capture／狀態，不是評分
        └── <scene>/
            ├── config.yaml
            ├── run_manifest.json        嘗試、hash、模型與完成狀態
            ├── camera_metadata.json
            ├── validation_report.json
            ├── visible/
            │   ├── observations/
            │   ├── graphs/view_1.json ...
            │   ├── prompts/
            │   └── responses/
            └── full/central_llm/
                ├── correspondence.md、correspondence.json
                ├── scene_graph.md
                ├── graphs/view_1.json ...
                ├── prompts/、responses/
                └── normalizations/
```

原始場景只保存在 basic，不隨實驗重複複製。實驗紀錄 capture_id 與來源目錄；
GT 保存輸入 SHA-256 與規則快照。模型的純圖片階段不讀 GT，中央階段只使用相機白名單及模型觀察。

## 現有程式的對應

| 舊位置 | 新位置／命令 |
| --- | --- |
| capture_scene.py | scene_capture/local/capture.py；`python3 -m scene_capture.local` |
| colab/AI2_THOR_Scene_Capture.ipynb | scene_capture/colab/AI2_THOR_Scene_Capture.ipynb |
| local/ | scene_capture/demo/；`python3 -m scene_capture.demo` |
| visible_ground_truth.py | gt/visible/generate.py；`python3 -m gt.visible` |
| full_ground_truth.py | gt/full/generate.py；`python3 -m gt.full` |
| ground_truth_common.py | gt/common.py |
| run_scene_graph.py | reasoning/pipeline.py；`python3 -m reasoning` |
| scene_prompts.py、scene_validation.py、ollama_client.py | reasoning/ 下的 prompts.py、validation.py、ollama_client.py |
| inspect_graph.py | visualization/inspect_graph.py；`python3 -m visualization` |

完整資料搬移表在 [data/migration_manifest.json](../data/migration_manifest.json)。
舊位置不建立可寫的 symlink，也不保留根目錄的重複程式；文件與測試使用新入口。

## 設定與紀錄

`--config` 讀取 YAML mapping，可省略。未指定時使用原有 CLI 預設值。
設定檔鍵名對應參數名稱的底線形式，例如 `image_size`、`scene_dir`、`no_html`。
未知鍵、錯誤型別、互斥設定會被拒絕。YAML 使用安全解析器；設定快照以 JSON 形式寫入 YAML，
這是合法 YAML 1.2，也能在不安裝 PyYAML 的情況下讀取。

遷移前的模型程式 hash 已改變，不能在新程式下直接 resume 舊結果。
歷史原始回應與 manifest 保留在 sample 的 legacy/，新的實驗使用新目錄。
JSON 匯出僅序列化已驗證回答，不建立新物件或做未授權的幾何推論。
