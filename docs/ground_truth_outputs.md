# GT 統一輸出與檢視

Visible GT 與 Full GT 的關係定義各自保留，但產生參數、檔案結構及 HTML 檢視方法相同。
Visible GT 需要 NumPy；Full GT 與檢查器只使用 Python 標準函式庫。

## 產生

```sh
python3 -m pip install -r requirements-ground-truth.txt
python3 visible_ground_truth.py --scene-dir colab/scene_output/20261105T120357_736949Z
python3 full_ground_truth.py --scene-dir colab/scene_output/20261105T120357_736949Z
```

兩種程式都有相同參數：

| 參數 | 用途 |
| --- | --- |
| `--scene-dir PATH` | 必填，Colab capture-v2 場景目錄 |
| `--view view_1 view_3` | 選擇一個或多個視角，省略時處理全部 |
| `--output-dir PATH` | 指定新的輸出目錄，拒絕覆寫既有目錄 |
| `--no-html` | 只輸出 JSON，不產生 HTML |

預設輸出為 `outputs/ground_truth/<scene_id>/<kind>-<UTC run_id>/`，
kind 為 visible 或 full。終端機同時印出輸出目錄與 HTML 路徑。

## 檔案結構

```text
<run>/
├── graphs/view_1.json ... view_4.json
├── measurements/view_1.json ... view_4.json
├── definitions.json
├── input_manifest.json
├── validation_report.json
├── review_tasks.json
└── inspect.html
```

兩種 GT 都使用 `graphs/`，不再以 visible/full/drafts 分開存圖。
每張圖使用相同 `schema_version=ground-truth-v1`，共同欄位為
graph_type、definition_version、view_id、status、review_task_count、nodes、edges。
graph_type 為 visible_ground_truth 或 full_ground_truth；兩種 GT 的測量欄位依各自算法保存。

| 檔案 | 內容 |
| --- | --- |
| `graphs/view_N.json` | 該視角的節點與四種關係 |
| `measurements/view_N.json` | 計算證據、相等配對及分類過程 |
| `definitions.json` | 本次使用的關係定義與版本 |
| `input_manifest.json` | 場景、實際輸入檔案及 SHA-256 |
| `validation_report.json` | 每視角的數量、狀態與待辦統計 |
| `review_tasks.json` | 統一以 id、view_id、objects、relation、reason 記錄人工待辦 |
| `inspect.html` | 已嵌入全部圖與證據的離線互動檢查器 |

有待辦的圖仍放在 graphs，status 為 needs_review，沒有待辦的圖為 complete。
兩種圖都逐視角判定，不因其中一張需要人工處理而隱藏其餘視角。
邊只保存已能確定的 accepted 關係，不產生 unresolved 邊。
status 不能藉手改字串就視為人工處理完成；本版尚未實作人工決定匯入器。

結束碼 `0` 表示全部所選視角完成；`1` 表示執行錯誤，未發布新的輸出目錄；
`2` 表示結果與 HTML 已輸出，但存在人工待辦。寫入時先完成整組檔案，再發布目錄。

## 檢視

直接用瀏覽器開啟輸出目錄中的 **inspect.html**。兩種 GT 操作完全相同：
切換視角、多選物件類型與關係、選擇所選物件之間或相關物件、查看證據與人工待辦。
草稿在選單、狀態列及匯出資料中保留標記，不能當作完整真值。

也能另存一份帶有初始篩選的檢查器，適用於兩種 GT：

```sh
python3 inspect_graph.py --run-dir <輸出目錄>
python3 inspect_graph.py --run-dir <輸出目錄> --view view_3 --types Apple Bowl CounterTop
python3 inspect_graph.py --run-dir <輸出目錄> --complete-only
```

新格式預設載入所有圖，`--complete-only` 只載入 complete 的視角。
HTML 是靜態快照，JSON 更新後需重新產生。用 `--no-open` 可避免嘗試啟動瀏覽器。

## 舊結果

舊版 visible/、full/、drafts/ 目錄仍可用 inspect_graph.py 讀取，原始結果不自動搬動。
舊格式需加 `--include-drafts` 才載入草稿；同一舊目錄有多種圖時以 `--graph-kind` 指定。
要取得統一格式，使用相同輸入場景重新執行產生器並指定新的輸出目錄。
