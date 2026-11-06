# 程式操作指南

所有指令從專案根目錄執行，使用 Python 3.10+。程式放在功能目錄，產生資料集中在 `data/`。

## 1. 選擇工作與入口

| 想做的事 | 指令入口 | 產物 |
| --- | --- | --- |
| 本機拍攝場景 | `python3 -m scene_capture.local` | basic/ 中的照片、metadata、mask、depth |
| Colab 拍攝 | scene_capture/colab/AI2_THOR_Scene_Capture.ipynb | 下載 ZIP，解壓縮到 capture 的 basic/ |
| 可見物件 GT | `python3 -m gt.visible` | 該視角可見節點與四種關係 |
| 全物件 GT | `python3 -m gt.full` | 全部物件相對指定相機的關係 |
| HTML 檢查器 | `python3 -m visualization` | 物件／關係篩選、證據與人工待辦 |
| VLM 推理 | `python3 -m reasoning` | 局部觀察、物件對應及 central_llm 的逐視角圖 |
| 固定任務示範 | `python3 -m scene_capture.demo` | 動作 JSON、選用影片 |

GT 與模型推理各自執行，不會把 GT 資料傳入模型提示。evaluate/ 預留評估功能，尚未產生評分。

## 2. 安裝與設定

```sh
python3 -m pip install -r requirements.txt -r requirements-ground-truth.txt
SCENE_DIR="data/scenes/sample/FloorPlan1/20261105T120357_736949Z/basic"
```

requirements.txt 提供 YAML 解析器；Visible GT 另需 NumPy。
Full GT、HTML 檢查器及模型流程使用純 CLI 時只需標準函式庫。
設定檔鍵名使用參數的底線名稱，例如 image_size、scene_dir、no_html，CLI 明確指定值優先。
每次結果都保存實際設定快照。省略 --config 時使用程式預設值。

| 模板 | 使用方式 |
| --- | --- |
| configs/capture.yaml | 拍攝用 --config |
| configs/gt.yaml | 兩種 GT 共用 --config |
| configs/experiments/baseline.yaml | 模型流程用 --config |

設定快照以 JSON 形式寫入 .yaml，為合法 YAML 1.2，也能用標準函式庫讀取。
不要把有不同模型參數的場景混入同一個 experiment ID。

## 3. 產生不同 GT

### 全部視角

```sh
python3 -m gt.visible --config configs/gt.yaml --scene-dir "$SCENE_DIR" --gt-id gt_example
python3 -m gt.full --config configs/gt.yaml --scene-dir "$SCENE_DIR" --gt-id gt_example
```

相同 gt-id 把兩種圖放在相同結果群組，分別保存於：

```text
data/scenes/sample/FloorPlan1/20261105T120357_736949Z/
├── basic/                       原始場景，不修改
└── gt/gt_example/
    ├── visible/
    └── full/
```

sample 也允許產生資料，但它會被 Git 追蹤；一般實驗可使用不在 sample 下的 capture。
省略 --gt-id 會自動使用 gt_<UTC時間>；兩次分開執行會產生不同 ID。
已存在的同種類結果不覆寫，重跑需更換 gt-id。

Visible GT 依各視角 mask 篩選節點；Full GT 保留全部 metadata 物件，包含不可見或畫面外物件。

| 關係 | Visible GT | Full GT |
| --- | --- | --- |
| on、inside | parentReceptacles＋父類型表，兩端須可見 | 相同父類型表，包含不可見端點 |
| image_left_of | 可見 mask 的平均 X | position 轉至相機座標後的水平投影 |
| closer_to_camera | mask 中有效原始深度中位數 | position 到 cameraPosition 的三維距離 |

兩種排序皆不設差距門檻。完全相等不建立方向邊，另存 equal_pairs。
Full 的相機後方／平面物件仍保留節點，但相關左右配對列為人工待辦。

### 指定視角

```sh
python3 -m gt.visible --scene-dir "$SCENE_DIR" --view view_3 --gt-id visible_view3
python3 -m gt.full --scene-dir "$SCENE_DIR" --view view_1 view_3 --gt-id full_view1_view3
```

只會產生所選視角的圖與測量檔，輸入仍需保留完整的 capture-v2 清單與可見聯集。

### 指定位置或略過 HTML

```sh
python3 -m gt.visible --scene-dir "$SCENE_DIR" --output-dir data/runs/gt-check-001/visible
python3 -m gt.full --scene-dir "$SCENE_DIR" --gt-id json_only --no-html
```

--output-dir 指的是這次結果目錄本身，必須尚未存在；--no-html 只略過 HTML。

### 產物與狀態

Visible／Full 每個結果目錄結構相同：

```text
<visible 或 full>/
├── config.yaml                         實際 CLI 設定
├── graphs/view_1.json ...               節點與關係
├── measurements/view_1.json ...         測量值、相等配對、分類過程
├── definitions.json                    關係規則快照
├── input_manifest.json                 capture 身分、來源及 SHA-256
├── validation_report.json              各視角數量、狀態與待辦統計
├── review_tasks.json                   人工待辦，沒有時為空清單
└── inspect.html                        除非指定 --no-html
```

status=complete 表示該視角完成，needs_review 表示草稿，兩者都在 graphs/。
每個視角獨立判定。結束碼 0 是全部完成；1 是執行錯誤；2 是結果已輸出但有人工待辦。
本批 Visible 四視角皆完成；Full 的 view_3 完成，view_1、view_2、view_4 尚有左右待辦。
尚未提供人工決定匯入器，不能直接手改 status 視為正式 GT。

## 4. 查看指定視角、物件與關係

直接以瀏覽器開啟終端機 Inspector: 顯示的 inspect.html。
已有的範例位於 sample capture 的 gt/gt_v1/visible/inspect.html 與 full/inspect.html。

```sh
GT_RUN="data/scenes/sample/FloorPlan1/20261105T120357_736949Z/gt/gt_v1/full"
python3 -m visualization --run-dir "$GT_RUN" --view view_3 --types Apple Bowl CounterTop \
  --relations on inside image_left_of closer_to_camera
```

HTML 可以切換視角、多選類型與關係、點選箭頭查看證據。圖的位置只是排版，不代表真實座標。
可選「所選物件之間」或「包含與其他物件的關係」，也可匯出篩選 JSON。

```sh
python3 -m visualization --run-dir "$GT_RUN" --types Apple Bowl --scope connected
python3 -m visualization --run-dir "$GT_RUN" --complete-only
python3 -m visualization --run-dir "$GT_RUN" --output data/runs/check-001/inspect.html --no-open
```

檢查器不重算 GT，預設另存 data/runs/inspection_<UTC>/inspect.html 並嘗試開啟瀏覽器。
HTML 是快照，圖更新後需重新產生。草稿保持狀態標示；舊 visible/full/drafts 格式也能讀取，
載入舊格式草稿需加 --include-drafts。

## 5. 收集新的場景

```sh
python3 -m pip install -r requirements.txt -r requirements-capture.txt
python3 -m scene_capture.local --config configs/capture.yaml --scene FloorPlan1 --headless
```

這會啟動 AI2-THOR。Linux headless 需可用的 Vulkan 驅動；若使用 X11，省略 --headless。

```sh
python3 -m scene_capture.local --scene FloorPlan1 --num-views 4 --image-size 800 \
  --output-dir data/scenes/FloorPlan1/capture_001/basic --zip
```

預設保存 data/scenes/<scene>/<UTC capture_id>/basic/。原始資料包含：
views.json、objects.json、visible_objects.json、RGB、各視角 metadata、depth、instance masks、
分割圖及對應表，另有僅供觀看的 view_00.png。capture_config.yaml 在 basic 的上一層。
--zip 另存 basic.zip；basic 目錄仍可直接交給 GT／模型流程。
每次拍攝使用新的 capture_id，避免改動已被實驗或 GT 引用的原始資料。

Colab 使用 scene_capture/colab/AI2_THOR_Scene_Capture.ipynb。
下載 ZIP 後解壓縮至 data/scenes/<scene>/<capture_id>/basic/，不在程式碼目錄存放成果。

## 6. 模型推理

先啟動 Ollama 並準備已安裝的影像模型；GT 流程不需要這一步。

```sh
# 一個終端機，服務已啟動可略過。
ollama serve
# 另一個終端機；使用新終端機時請重新設定 SCENE_DIR。
ollama pull gemma4:e4b
python3 -m reasoning --config configs/experiments/baseline.yaml --scene-dir "$SCENE_DIR"
```

### 只檢查輸入，不呼叫模型

```sh
python3 -m reasoning --scene-dir "$SCENE_DIR" --dry-run
```

仍會產生新實驗、相機白名單與提示，不會產生完成的模型圖。

### 指定實驗 ID

```sh
python3 -m reasoning --scene-dir "$SCENE_DIR" --experiment-id exp_001
```

輸出到 data/runs/exp_001/<scene>/。預設 ID 為 exp_<UTC>。
可在同一 ID 加入不同場景，需保持實驗設定相同；同一 scene 不可覆寫或改用另一個 capture，
應使用新的 experiment ID。

```text
<experiment>/
├── config.yaml                        共用實驗設定
├── run_manifest.json                  場景、capture 與狀態索引
├── summary.csv                        只記錄真實狀態，尚無評分
└── <scene>/
    ├── config.yaml、run_manifest.json
    ├── camera_metadata.json、validation_report.json
    ├── visible/
    │   ├── observations/view_1.md ...
    │   ├── graphs/view_1.json ...
    │   ├── prompts/、responses/
    └── full/central_llm/
        ├── correspondence.md、correspondence.json
        ├── scene_graph.md
        ├── graphs/view_1.json ...
        ├── prompts/、responses/
        └── normalizations/
```

目前模型流程要求恰好四張圖。單視角 JSON 保留模型原本的自然語言關係，
尚未新增語意轉換；central_llm 的逐視角 JSON 保留全部全域節點，只選 physical 或目標視角的邊，
不把另一視角的左右關係直接改標為目標視角。其他合併方法及評估器仍待設計。

### 續跑與 fork

```sh
MODEL_RUN="data/runs/exp_001/FloorPlan1"
python3 -m reasoning --scene-dir "$SCENE_DIR" --resume "$MODEL_RUN"
python3 -m reasoning --scene-dir "$SCENE_DIR" --fork-from "$MODEL_RUN"
```

resume 指向場景結果目錄，核對輸入、程式及模型設定，只繼續缺少工作；dry-run 不能續跑。
fork 建立新實驗並重驗可重用結果，保留原紀錄。設定有變時請在指令中給出與來源相同的參數。
遷移前的原始模型範例保存在 data/runs/sample/ 下的 legacy/，原始 capture 不在專案內，
場景以 unidentified_scene 標示，不可直接當作目前場景的評分結果。
GT HTML 檢查器目前只解析 GT JSON，不解析模型的 Markdown 或局部觀察 JSON。

## 7. 固定任務示範與測試

```sh
python3 -m pip install -r scene_capture/demo/requirements.txt
python3 -m scene_capture.demo --headless --output-dir data/runs/demo_001/FloorPlan1/demo
```

需可執行模擬器；輸出 trace_log.json 與 run.mp4。加 --no-video 只保存 JSON。
這個固定動作示範不自動使用場景圖。新實驗請指定新目錄，詳細資訊見 [示範說明](demo.md)。

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
```

測試使用暫存目錄、假模型／controller，不需要模型或 Unity；HTTP 測試會啟動 localhost。

## 8. 哪些資料會上傳 GitHub

- data/scenes/sample/：Git 追蹤的場景範例，包含 basic 與 GT。
- data/runs/sample/：Git 追蹤的歷史實驗與示範。
- 其他 data/scenes/、data/runs/ 子目錄：Git 忽略，供一般拍攝與實驗使用。

data/migration_manifest.json 記錄本次資料搬移對應。來源檔原始位元組保留，
新 GT 範例已重算驗證，歷史原始模型紀錄保存在 legacy/ 以便回查。
