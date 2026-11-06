# Multiview Scene Graph

從 AI2-THOR 收集多視角場景，分別執行 VLM 推理與 Ground Truth 計算。
程式碼按功能分組，拍攝資料、GT 與實驗結果集中於 `data/`。

## 文件

- [操作指南](docs/operation_guide.md)：依工作查指令、輸入及輸出。
- [架構與遷移](docs/architecture.md)：目錄、模組對應及歷史成果。
- [GT 輸出與檢視](docs/ground_truth_outputs.md)、[Visible GT](docs/ground_truth_relations.md)、[Full GT](docs/full_ground_truth.md)。
- [本機拍攝](docs/local_capture.md)、[Colab 匯出](docs/colab_capture.md)。
- [Ollama 推理](docs/ollama_guide.md)、[模型輸出格式](docs/output_format.md)、[研究設計](docs/research_design.md)。
- [固定任務示範](docs/demo.md)。

## 目錄

```text
configs/                       拍攝、GT、實驗的 YAML 設定
scene_capture/colab/            獨立 Colab Notebook
scene_capture/local/            本機拍攝 CLI
scene_capture/demo/             固定機器人任務示範
reasoning/visible/              單視角觀察與 JSON 匯出
reasoning/full/methods/         跨視角方法，目前提供 central_llm
reasoning/pipeline.py          模型流程、重試、續跑與紀錄
reasoning/ollama_client.py     Ollama 通訊
reasoning/prompts.py           提示模板
reasoning/validation.py        模型回答驗證與正規化
gt/visible/、gt/full/           兩種 GT 產生器
gt/common.py                   GT 共用規則、輸出及 CLI
visualization/                 HTML 檢查器
common/                        資料路徑、設定讀取與快照
evaluate/                      評估模組預留，尚未實作
data/scenes/                   場景與 GT
data/runs/                     實驗、檢查器及歷史紀錄
docs/、tests/                  文件與測試
```

所有命令從專案根目錄執行，使用 Python 3.10+。

## 產生 GT

```sh
# YAML 設定與 Visible GT 的依賴；Full GT 使用純 CLI 時只需標準函式庫。
python3 -m pip install -r requirements.txt -r requirements-ground-truth.txt
SCENE_DIR="data/scenes/sample/FloorPlan1/20261105T120357_736949Z/basic"
python3 -m gt.visible --scene-dir "$SCENE_DIR" --gt-id gt_example
python3 -m gt.full --scene-dir "$SCENE_DIR" --gt-id gt_example
```

兩者共用參數：`--config`、`--view`、`--gt-id`、`--output-dir`、`--no-html`。
相同 `--gt-id` 可把兩種 GT 放在同一組結果：

```text
data/scenes/[sample/]<scene>/<capture_id>/
├── basic/                         原始資料，拍攝後保持不變
└── gt/<gt_id>/
    ├── visible/
    └── full/                      與 visible 相同結構
        ├── graphs/view_1.json ...
        ├── measurements/view_1.json ...
        ├── config.yaml
        ├── definitions.json
        ├── input_manifest.json
        ├── validation_report.json
        ├── review_tasks.json
        └── inspect.html
```

直接以瀏覽器開啟 `inspect.html`。圖以 `complete`／`needs_review` 標示狀態，
有人工待辦時程式結束碼為 `2`，結果仍已輸出。這批 Full GT 的 view_3 完成，其他視角
的相機後方左右配對保留待辦。既有可直接瀏覽的範例為 `gt/gt_v1/visible/inspect.html`
及 `gt/gt_v1/full/inspect.html`。

```sh
python3 -m visualization --run-dir "$SCENE_DIR/../gt/gt_v1/full" --view view_3 --types Apple Bowl CounterTop
```

## 拍攝資料

```sh
python3 -m pip install -r requirements.txt -r requirements-capture.txt
python3 -m scene_capture.local --config configs/capture.yaml --scene FloorPlan1 --headless
```

需具備 AI2-THOR 與可用的渲染環境。Linux `--headless` 使用 Vulkan，不需 X11。
預設保存到 `data/scenes/<scene>/<UTC capture_id>/basic/`，設定快照在同一 capture 目錄。
Colab 使用 `scene_capture/colab/AI2_THOR_Scene_Capture.ipynb`，下載後解壓縮至相同的 basic 結構。

## 模型推理

```sh
# 準備 Ollama 服務及已安裝的影像模型後執行。
python3 -m reasoning --config configs/experiments/baseline.yaml --scene-dir "$SCENE_DIR"
# 只檢查輸入並保存提示，不呼叫模型。
python3 -m reasoning --scene-dir "$SCENE_DIR" --dry-run
```

預設輸出 `data/runs/exp_<UTC>/<scene>/`，包含單視角觀察、各視角 JSON、
`full/central_llm/` 的對應與逐視角 JSON，以及原始 prompts／responses。
實驗根目錄有設定快照、場景索引與 `summary.csv`（目前只彙總狀態，不含未實作的評分）。
同一實驗可用 `--experiment-id exp_001` 加入不同場景；相同場景不得覆寫。
單視角的自然語言關係忠實保留，尚未新增自動的四關係語意轉換。

## Sample 與 Git

`data/scenes/sample/`、`data/runs/sample/` 會被 Git 追蹤，可上傳 GitHub；
其他場景與實驗預設忽略。`data/migration_manifest.json` 記錄舊位置到新位置的對應。
原 Colab 範例原始檔保持位元組一致；歷史模型回答仍完整保存在 sample 實驗的 `legacy/`。
原始來源場景缺失的歷史實驗以 `unidentified_scene` 標記，不推測它與目前 GT 的對應。

## 測試

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
```

不需要實際模型或模擬器。拍攝測試以假 controller 驗證匯出；HTTP 測試使用 localhost。
