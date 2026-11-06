# 程式操作指南

本文件以「要做什麼 → 執行什麼指令 → 會產生什麼」說明目前的程式。
指令以 Linux 的 `python3` 為例，除本機模擬器章節外，都在專案根目錄執行。

## 1. 先選擇要執行的工作

| 想做的事 | 使用程式 | 是否需要模型 | 主要產物 |
| --- | --- | --- | --- |
| 擷取場景與照片 | Colab Notebook | 否 | 照片、metadata、遮罩、深度、可見清單 |
| 產生各視角 Visible GT | `visible_ground_truth.py` | 否 | 可見物件圖、測量證據、HTML |
| 產生各視角 Full GT | `full_ground_truth.py` | 否 | 全物件圖、幾何證據、人工待辦、HTML |
| 檢查 GT 中特定物件的關係 | `inspect_graph.py` | 否 | 可篩選的獨立 HTML |
| 用照片進行模型建圖 | `run_scene_graph.py` | 需要 Ollama | 局部觀察、跨視角對應、模型場景圖與紀錄 |
| 執行固定機器人任務示範 | `local/main.py` | 否 | 動作紀錄、選用影片 |

GT 計算與模型推理是兩條獨立流程。執行 GT 產生器不會呼叫 Ollama，
執行模型建圖也不會自動產生 GT 或計算評分。目前尚未實作自動比較模型圖與 GT 的評分器。

## 2. 準備場景資料與環境

在 Colab 開啟 [AI2_THOR_Scene_Capture.ipynb](../colab/AI2_THOR_Scene_Capture.ipynb)，
依 Notebook 執行環境啟動、拍攝及下載。將 ZIP 解壓縮至 `colab/scene_output/`。
Colab 只收集資料，不在拍攝階段產生場景圖。匯出細節見 [Colab 說明](colab_capture.md)。

本文件使用這批已存在的資料，在同一個終端機先設定路徑：

```sh
SCENE_DIR="colab/scene_output/20261105T120357_736949Z"
```

目錄中應包含：

```text
views.json                        視角與檔案清單、相機資訊
objects.json                      全部物件 metadata
visible_objects.json              所有視角的可見物件聯集
view_01.png ... view_04.png        一般視角照片
metadata_01.json ...               每次拍攝的完整 metadata
depth_01.npy ...                   原始深度陣列
instance_masks_01.npz ...          物件可見遮罩
segmentation_mapping_01.json ...   物件 ID、遮罩 key 與像素數對應
```

`view_00.png` 是俯視參考圖，不參與建圖計算。
`visible_objects.json` 是跨視角聯集，各張 Visible GT 還會依 `visible_views` 篩選。

Python 需為 3.10+。首次要執行 Visible GT 或完整測試時，安裝 NumPy：

```sh
python3 -m pip install -r requirements-ground-truth.txt
```

Full GT、HTML 檢查器與根目錄的模型建圖程式只使用 Python 標準函式庫。
Ollama 及 AI2-THOR 是各自流程的額外執行環境，不是產生 GT 的共同前置條件。

## 3. 產生 Visible GT

### 全部視角

```sh
python3 visible_ground_truth.py --scene-dir "$SCENE_DIR"
```

這批四視角資料會產生四張圖。每張圖的節點只包含該視角可見的物件，關係兩端都必須可見。

| 關係 | 計算來源 |
| --- | --- |
| `on`、`inside` | parentReceptacles 與父物件類型對應表 |
| `image_left_of` | 同一視角的可見遮罩中心 X |
| `closer_to_camera` | 遮罩內有效原始深度的中位數 |

預設輸出為：

```text
outputs/ground_truth/20261105T120357_736949Z/visible-<UTC時間>/
```

終端機會印出 `Output:` 與 `Inspector:`，後者就是可以直接用瀏覽器開啟的 HTML。
這批資料的可見節點數依序為 11、23、56、43，全部可完成，沒有人工待辦。

### 只產生指定視角

```sh
# 一個視角，只輸出 view_3 的圖與測量檔。
python3 visible_ground_truth.py --scene-dir "$SCENE_DIR" --view view_3

# 多個視角，只輸出 view_1、view_4。
python3 visible_ground_truth.py --scene-dir "$SCENE_DIR" --view view_1 view_4
```

即使只選一個視角，輸入仍需保留完整 capture-v2 場景清單及對應的可見聯集資料。

## 4. 產生 Full GT

### 全部視角

```sh
python3 full_ground_truth.py --scene-dir "$SCENE_DIR"
```

每張圖都包含全部 metadata 物件，這批資料每張有 77 個節點。
不可見或位於畫面外的物件不會被刪除。

| 關係 | 計算來源 |
| --- | --- |
| `on`、`inside` | parentReceptacles 與相同父物件類型對應表 |
| `image_left_of` | 物件 position 轉換至指定相機後的水平投影位置 |
| `closer_to_camera` | 物件 position 到 cameraPosition 的三維直線距離 |

預設輸出為：

```text
outputs/ground_truth/20261105T120357_736949Z/full-<UTC時間>/
```

Visible 的遠近比較可見表面深度，Full 比較物件位置距離，兩者採不同測量定義。
對相機後方或相機平面上的物件，Full 仍保留節點及可計算的關係，
但其相關左右配對會進入人工待辦，圖的狀態為 `needs_review`。

### 只產生指定視角

```sh
python3 full_ground_truth.py --scene-dir "$SCENE_DIR" --view view_3
python3 full_ground_truth.py --scene-dir "$SCENE_DIR" --view view_1 view_3
```

只選 view_3 時，本批資料可以完整產生 77 個節點、5,888 條關係，沒有人工待辦。
選全部視角時，view_1、view_2、view_4 仍會產生圖，但標示為草稿。

## 5. 兩種 GT 共用的輸出選項

### 指定輸出位置

以下範例要使用尚未存在的目錄；再次執行時換一個名稱：

```sh
python3 visible_ground_truth.py --scene-dir "$SCENE_DIR" \
  --output-dir outputs/ground_truth/my-visible-01

python3 full_ground_truth.py --scene-dir "$SCENE_DIR" \
  --output-dir outputs/ground_truth/my-full-01
```

省略 `--output-dir` 會自動建立帶 UTC 時間的新目錄。兩種程式都不會覆寫既有目錄。
GT 的 `--output-dir` 指的是本次結果目錄本身。

### 只產生 JSON

```sh
python3 visible_ground_truth.py --scene-dir "$SCENE_DIR" --no-html
python3 full_ground_truth.py --scene-dir "$SCENE_DIR" --no-html
```

會產生相同的 JSON 檔案，但略過 `inspect.html`。之後仍可使用檢查器另外產生 HTML。

### 輸出檔案

兩種 GT 的結構相同；只選部分視角時，只會出現那些視角的圖及測量檔。

```text
<本次輸出目錄>/
├── graphs/view_1.json ... view_4.json
├── measurements/view_1.json ... view_4.json
├── definitions.json
├── input_manifest.json
├── validation_report.json
├── review_tasks.json
└── inspect.html
```

| 檔案 | 會產生的內容 |
| --- | --- |
| `graphs/view_N.json` | 節點、關係、圖種類及完成狀態 |
| `measurements/view_N.json` | 測量值、相等配對、父物件分類等證據 |
| `definitions.json` | 本次使用的規則及版本 |
| `input_manifest.json` | 場景路徑、實際輸入檔案及 SHA-256 |
| `validation_report.json` | 各視角的節點數、各類關係數及待辦統計 |
| `review_tasks.json` | 需要人工判定的內容；沒有待辦時為空清單 |
| `inspect.html` | 已嵌入圖及證據的離線互動檢查器，除非指定 `--no-html` |

圖的 `status=complete` 表示該視角已完成；`needs_review` 表示仍有人工待辦。
兩者都放在 `graphs/`，每個視角獨立標示狀態。

| 程式結束碼 | 意義 |
| --- | --- |
| `0` | 所選視角全部完成 |
| `1` | 資料或執行錯誤，未發布新的結果目錄 |
| `2` | 結果已輸出，但仍有人工待辦；不是整次計算失敗 |

相等值不建立任一方向的排序邊，另記錄在測量檔，不屬於人工待辦。
目前會輸出人工清單，尚未提供人工決定的匯入器。

## 6. 檢視特定視角與物件關係

### 直接檢視

用瀏覽器開啟剛才終端機 `Inspector:` 顯示的 `inspect.html`。
Visible GT 與 Full GT 操作相同，可以切換視角、多選物件類型與四種關係，
並選擇「只看所選物件之間」或「包含與其他物件的關係」。
點箭頭、節點或清單中的「證據」可查看完整 ID 與測量值。
圖形排版的位置不代表物件的實際座標；Full 圖中橘色虛線外框代表該視角不可見。

### 另外產生帶有初始篩選的 HTML

先將 `GT_RUN` 設為剛才 `Output:` 印出的目錄。以下以已存在的 Visible GT 示範：

```sh
GT_RUN="outputs/ground_truth/20261105T120357_736949Z/visible-unified-v1"
python3 inspect_graph.py --run-dir "$GT_RUN"
```

改看 Full GT，只需更換路徑，指令相同：

```sh
GT_RUN="outputs/ground_truth/20261105T120357_736949Z/full-unified-v1"
python3 inspect_graph.py --run-dir "$GT_RUN"
```

指定視角、物件類型及關係：

```sh
python3 inspect_graph.py --run-dir "$GT_RUN" \
  --view view_3 --types Apple Bowl CounterTop \
  --relations on inside image_left_of closer_to_camera
```

這只設定 HTML 開啟時的初始篩選，之後仍可在介面調整，不會修改原圖。

```sh
# 查看 Apple、Bowl 與其他物件之間的物理關係。
python3 inspect_graph.py --run-dir "$GT_RUN" \
  --types Apple Bowl --relations on inside --scope connected

# 只載入已完成視角；本批 Full GT 只會載入 view_3。
python3 inspect_graph.py --run-dir "$GT_RUN" --complete-only

# 不啟動瀏覽器，另存一份 HTML；指定檔案必須不存在。
python3 inspect_graph.py --run-dir "$GT_RUN" \
  --output outputs/graph_inspection/my-check-01.html --no-open
```

檢查器預設另存 `outputs/graph_inspection/<UTC時間>.html` 並嘗試開啟瀏覽器。
它讀取已計算的圖與測量值，不會重算 GT。HTML 是靜態快照，更新 JSON 後需重新產生。
介面的「匯出篩選 JSON」會由瀏覽器下載目前結果，不會修改原始 GT。
新格式預設包含草稿；舊版 `visible/`、`full/`、`drafts/` 結構仍能讀取，
讀取舊版草稿時加上 `--include-drafts`。

## 7. 以 VLM 推理產生場景圖

此操作使用模型看照片，產物是推理結果，不是 GT。此版要求恰好四張一般視角圖片。

### 只檢查輸入與提示，不呼叫模型

```sh
python3 run_scene_graph.py --scene-dir "$SCENE_DIR" --dry-run
```

產生新的 `outputs/<UTC時間>/`，保存相機白名單、提示與執行紀錄，
不會有完成的模型觀察、物件對應或場景圖。dry-run 目錄不能用來續跑推理。

### 執行完整推理

先準備本機 Ollama。以下兩個服務準備動作分別操作，服務需維持執行：

```sh
# 一個終端機；若服務已啟動可略過。
ollama serve
```

```sh
# 另一個終端機，模型已安裝可略過。
ollama pull gemma4:e4b
python3 run_scene_graph.py --scene-dir "$SCENE_DIR"
```

若使用新的終端機，先重新設定本文件前面的 `SCENE_DIR`。
預設模型是 `gemma4:e4b`，可用 `--model` 指定已安裝且支援影像的模型。

完整流程依序產生：

| 產物 | 內容 |
| --- | --- |
| `observations/view_1.md`～`view_4.md` | 四次獨立看圖的局部觀察 |
| `correspondence.md` | 跨視角的物件對應 |
| `scene_graph.md` | 模型整合的初版場景圖 |
| `camera_metadata.json` | 送給中央模型的相機白名單 |
| `prompts/`、`responses/` | 實際提示、原始回答及 API 回應 |
| `normalizations/` | 發生正規化時的修改紀錄 |
| `run_manifest.json`、`validation_report.json` | 設定、來源、執行及格式驗證紀錄 |

這些檔案預設存於 `outputs/<UTC時間>/`。模型流程的 `--output-dir` 是存放各次 run 的
父目錄，與 GT 的「本次結果目錄」含義不同。GT HTML 檢查器目前不解析模型 Markdown 圖。

### 中斷後續跑

將 `MODEL_RUN` 換成實際的推理 run 目錄：

```sh
MODEL_RUN="outputs/本次推理的時間目錄"
python3 run_scene_graph.py --scene-dir "$SCENE_DIR" --resume "$MODEL_RUN"
```

會核對輸入、程式及模型設定，保留有效的完成結果，只繼續缺少的工作。
程式改版後的恢復可使用 `--fork-from`，細節見 [Ollama 指南](ollama_guide.md)。

## 8. 本機固定任務示範

此操作需要可執行 AI2-THOR 的電腦，與 GT 產生器獨立，不會自動讀取場景圖。

```sh
cd local
python3 -m pip install -r requirements.txt
python3 main.py --output-dir outputs/my-task-01
```

會依固定腳本執行 FloorPlan1 任務，產生 `local/outputs/my-task-01/trace_log.json`
與 `run.mp4`。同一目錄的同名紀錄會被覆寫，請為不同實驗指定不同目錄。

```sh
# 不錄影，只保存 JSON；Linux 離屏模式另需可用 Vulkan 驅動。
python3 main.py --headless --no-video --output-dir outputs/my-task-02
```

關於模擬器環境、任務內容及參數，見 [local 說明](../local/README.md)。

## 9. 驗證程式

回到專案根目錄，執行離線測試，不需要模型或模擬器：

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
```

只檢查某個功能：

```sh
python3 -m unittest discover -s tests -p 'test_visible_ground_truth.py' -v
python3 -m unittest discover -s tests -p 'test_full_ground_truth.py' -v
python3 -m unittest discover -s tests -p 'test_inspect_graph.py' -v
```

測試使用暫存目錄，不會建立新的正式 GT run；本機存在範例場景時，會額外驗收實際場景數量。
完整測試中的 HTTP client 測試會啟動短暫的 localhost 測試服務，不連線到實際 Ollama。
