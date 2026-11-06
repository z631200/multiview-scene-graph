# Visible ground-truth 產生器

`visible_ground_truth.py` 從 Colab capture-v2 匯出資料產生各視角 Visible GT，
不呼叫 AI，也不執行模擬器。[Full GT](full_ground_truth.md) 由獨立程式產生；合併推理及模型評分不在此程式範圍。
此文件取代先前要求幾何接觸證據、差距門檻及 unresolved 的 GT 草案。

## 執行

Python 3.10+，需要 NumPy：

```sh
python3 -m pip install -r requirements-ground-truth.txt
python3 visible_ground_truth.py \
  --scene-dir colab/scene_output/20261105T120357_736949Z
```

預設輸出 `outputs/ground_truth/<scene_id>/<UTC run_id>/`。
可用 `--output-dir PATH` 指定新的目錄，既有目錄一律拒絕覆寫。
依清單處理全部一般視角；四視角輸入會得到四張圖，亦支援 capture-v2 的三視角資料。
`view_00.png` 不參與計算。

## 資料檢查與可見範圍

- 讀取 `objects.json` 的完整物件與父容器資料。
- 驗證 `visible_objects.json` 是 `visible_views` 非空的完整聯集，再依 view ID 篩選。
- 各視角 metadata 必須與彙總快照具有一致的物件 ID、類型、位置、旋轉、AABB 及父容器關係。
- 驗證照片標頭尺寸、深度與遮罩形狀、遮罩布林型別、NPZ 的物件順序與 key、
  遮罩像素數、mapping 與可見清單一致。照片不需要解碼；空視角可以有空節點與空邊。
- 所有輸入檔案路徑必須位於場景目錄內。輸出保存實際使用檔案的 SHA-256。
- 不使用 metadata 的原生 `visible` 作為畫面可見性；完整 metadata 的這個欄位可受距離限制。

節點只包含該視角可見物件，沿用原始 `objectId`。每條邊的兩端都必須在節點中。
可見子物件的不可見父容器不會新增為節點，其關係另記於 `excluded_parent_relations`。

## 四種關係

版本：`visible-parent-mask-depth-v1`。規則在程式的 `DEFINITIONS` 與
`ground_truth_common.py` 的 `PARENT_RELATIONS` 中定義，每次執行另存 `definitions.json` 快照。

### on / inside

只處理 `parentReceptacles` 明確列出的父物件。可見子物件的候選先記為 `on`，
再以父物件 `objectType` 覆寫；處理紀錄保存初始與最終分類。

| 父物件類型 | 最終關係 |
| --- | --- |
| CounterTop、Floor | on |
| Cabinet、Fridge、Drawer、Shelf | inside |

這是本研究指定的類型分類規則，不額外以 AABB 驗證實際支撐或完整包含。
每個父子配對只輸出表中決定的一種關係；有多個父物件時分別處理。
沒有父容器則沒有此類邊，不因可見性臆造關係；未知類型交人工處理。
參考系為 `physical`。

### image_left_of

取同一視角每個物件所有可見遮罩像素的 column index 平均值，單位為像素，
零點在圖片左側。比較所有不同物件配對，X 較小者指向較大者。
不採 bounding box 中點，也不比較世界座標。參考系為該 view ID。

### closer_to_camera

取物件遮罩內有限且大於零的原始深度像素，以 float64 計算中位數，單位公尺。
中位數較小者指向較大者。保留 AI2-THOR 原生深度定義，不宣稱它是物件中心距離，
也不在此程式轉換成相機軸向深度。有效／無效像素數均保存。
參考系為該 view ID。沒有任何有效深度時交人工處理。

兩種排序都使用嚴格 `<`，不設差距門檻。完全相等時兩個方向皆不建邊，
在 `equal_pairs` 中記錄配對、關係及測量值；相等不屬於待處理案例。
不建立自身關係，不額外做遞移補邊。

## 輸出與人工處理

```text
<run>/
├── definitions.json
├── input_manifest.json
├── validation_report.json
├── review_tasks.json
├── measurements/view_1.json ...
└── visible/view_1.json ...
```

圖格式為 `visible-gt-v1`，包含 `graph_type`、`view_id`、`definition_version`、
`status`、`nodes`、`edges`。節點保存 `id`、`objectType`、`name`；邊保存
`id`、`source`、`relation`、`target`、`frame`、`status=accepted`、
`definition_version`、`evidence`。物理邊引用 metadata 與父物件類型；
排序邊保存兩端數值並引用輸出根目錄下的 measurements 檔案。

Measurements 保存各物件像素數、遮罩中心、深度中位數及有效像素數、
相等配對、不可見父容器的排除紀錄，以及父物件分類過程。

- 結束碼 `0`：全部視角完成，正式圖存於 `visible/`，人工清單為空。
- 結束碼 `1`：資料缺漏、不一致或寫入失敗；不發布新的完成目錄。
- 結束碼 `2`：需要人工處理；圖放在 `drafts/`，沒有 `visible/`。
  受影響圖及總報告標示 `needs_review`，已能確定的邊仍為 accepted；不產生 unresolved 邊。

任何待處理案例都會阻止本次整組正式圖發布。此版只產生人工清單，尚未提供
人工覆寫匯入功能；不能直接把草稿改名當作正式圖。全部檔案序列化完成後才發布輸出目錄。

## 場景驗收：20261105T120357_736949Z

場景共有 77 個物件，跨視角可見聯集為 67 個。所有父容器類型皆在分類表中。

| 視角 | 節點 | on | inside | image_left_of | closer_to_camera | 總邊數 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| view_1 | 11 | 8 | 0 | 55 | 55 | 118 |
| view_2 | 23 | 15 | 0 | 253 | 253 | 521 |
| view_3 | 56 | 25 | 4 | 1540 | 1530 | 3099 |
| view_4 | 43 | 16 | 1 | 903 | 903 | 1823 |

view_3 有 10 對相等深度，不建立遠近邊。view_4 的
`Vase|+01.99|+00.56|-02.49` 可見，但其父物件 `Shelf|+01.75|+00.55|-02.56`
不可見，因此不建立此條 inside 邊。這兩種情況都有明確紀錄，不需人工裁定。

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -p 'test_visible_ground_truth.py' -v
```

測試涵蓋關係方向、六種父物件分類、不可見父物件、空視角、相等值、無效深度、
人工處理阻擋發布、輸入不一致與覆寫保護；本機存在上述場景時另驗收四張圖的實際數量。

## 互動檢查場景圖

`inspect_graph.py` 只使用 Python 標準函式庫，讀取已產生的 GT run，輸出可離線開啟的
單一 HTML 檔，並嘗試開啟瀏覽器。不需要安裝網頁套件或啟動服務。

```sh
python3 inspect_graph.py \
  --run-dir outputs/ground_truth/20261105T120357_736949Z/visible-v1

# 也可指定初始篩選；之後仍能在介面切換。
python3 inspect_graph.py \
  --run-dir outputs/ground_truth/20261105T120357_736949Z/visible-v1 \
  --view view_3 --types Apple Bowl CounterTop \
  --relations on inside image_left_of closer_to_camera
```

- 視角下拉選單：切換各張圖。
- 物件類型：可搜尋、多選；同類型不同實體分開編號並保留 objectId。
- 顯示範圍：預設只顯示所選類型之間的關係，也可包含所選物件與其他物件的關係。
- 關係：四種關係可獨立勾選；預設開啟 on、inside。
- 圖形：支援拖曳、縮放；節點為圓形排版，位置不代表實際空間座標。
- 證據：點選箭頭、節點或關係清單，檢查完整 ID、關係來源與兩端測量值。
- 相等配對與不可見父物件的排除紀錄：另行列出，依同一組條件篩選。
- 匯出篩選 JSON：包含當前節點、邊、計算紀錄及所用篩選條件。

預設輸出為 `outputs/graph_inspection/<UTC>.html`。可用 `--output PATH` 指定檔名，
已有檔案不覆寫；`--no-open` 只產生檔案，供遠端或無桌面環境使用。
檢查器預設讀取 `visible/` 或 `full/` 的正式 JSON 圖，可用 `--graph-kind visible|full`
指定種類；加上 `--include-drafts` 可瀏覽草稿及人工待辦。草稿在介面與匯出的篩選 JSON
中都保留狀態，不會被當成完整真值。尚不解析 VLM 的 Markdown 輸出。
