# Full ground-truth

`full_ground_truth.py` 以 capture-v2 匯出資料計算指定相機下全部物件的場景圖。
僅需 Python 3.10+ 標準函式庫，不使用模型、RGB、遮罩或深度圖來推斷關係。
`ground_truth_common.py` 提供 Visible／Full 共用的檔案讀取、父物件分類及輸出工具。

## 執行與輸出

```sh
# 預設產生全部視角，以及共用現有介面的 HTML 檢查器。
python3 full_ground_truth.py --scene-dir colab/scene_output/20261105T120357_736949Z

# 指定一個或多個視角。
python3 full_ground_truth.py --scene-dir colab/scene_output/20261105T120357_736949Z --view view_1 view_3
```

可用 `--output-dir PATH` 指定新目錄，既有目錄不覆寫；`--no-html` 略過 HTML。
預設輸出為 `outputs/ground_truth/<scene_id>/full-<UTC run_id>/`：

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

與 Visible GT 共用 [統一輸出格式與檢視方式](ground_truth_outputs.md)。
圖格式為 `ground-truth-v1`，`graph_type=full_ground_truth`；所有圖統一放在 `graphs/`。
每個視角獨立判定完成，以圖內 status 區分完成與草稿，不因其他視角的待辦而隱藏已完成的圖。
結束碼 `0` 表示所選視角全部完成，`1` 表示輸入／執行錯誤，`2` 表示已有輸出但仍需人工處理。
輸入錯誤不會發布新的輸出目錄。

## 節點與資料檢查

節點包含 `objects.json` 的全部物件，使用原始 objectId。
`visible_objects.json` 用於核對可見聯集，不用於縮減節點。
每個節點記錄 `visible_in_view`、`ever_visible` 和 `camera_region`（front／behind／camera_plane）。
可見性依 `visible_views`，不使用模擬器受距離限制的原生 visible。

指定視角 metadata 的物件清單、類型、位置、旋轉、父容器、AABB 必須與彙總快照一致；
相機欄位也必須在 `views.json` 的 camera、舊相容欄位及該視角 metadata 間一致。
檢查座標有限、視角存在、父物件 ID 有效、單位為公尺／度、FOV 介於 0 與 180 度。
此版本支援 yaw 與 cameraHorizon，遇到非零 agent pitch／roll 會明確拒絕，不會靜默忽略。
每個已讀取的來源檔案保存 SHA-256；未選取視角的 metadata 不作為本次輸入。

## 關係定義

規則版本為 `full-parent-position-camera-v1`，每次執行保存 `definitions.json`。

### on / inside

僅處理明確的 parentReceptacles。從未可見者初始分類為 inside，其他物件初始分類為 on，
再以父物件類型覆寫。CounterTop、Floor → on；Cabinet、Fridge、Drawer、Shelf → inside。
初始與最終分類均保存。沒有父容器就不建立此類邊，未知類型交人工處理。
同一場景的物理關係在不同視角一致，不因畫面可見性改變。

### image_left_of

以物件 position 為判定點。相對相機位移為 dx、dy、dz；yaw 為 θ，向下俯仰角為 φ：

```text
h  = sin(θ) * dx + cos(θ) * dz
Xc = cos(θ) * dx - sin(θ) * dz
Yc = cos(φ) * dy + sin(φ) * h
Zc = cos(φ) * h - sin(φ) * dy
```

當兩物件 Zc 都大於零，比較 Xc/Zc，較小者指向較大者。
另以垂直 FOV、圖片尺寸計算投影像素位置，供人工檢查；關係直接比較比例，避免像素
換算的額外捨入。畫面外的位置不裁切；position_in_frame 只描述判定點是否落在影像內，
不代表物件實際可見。

任一端點 Zc <= 0 時，不建立該配對的左右邊，另建立人工待辦。
節點及其他可計算關係仍保留。恰為 0／90／180／270 度的三角函數使用精確值，
避免浮點殘值把相機平面上的點誤分到前方；其他角度不使用差距門檻。

AABB 只記錄角點的相機深度範圍及是否跨越相機平面；不替換 position，
也不因大型 Floor 的包圍盒跨越相機平面就取消其正深度中心的排序。

### closer_to_camera

採物件 position 到 cameraPosition 的三維直線距離，包含相機後方物件。
實作比較平方距離（平方公尺），並保存距離（公尺）；平方比較避免額外平方根捨入。
此定義與 Visible GT 的可見表面原始深度中位數不同，兩者不可當成同一測量值。

兩種排序均採嚴格 `<`，不設差距門檻。完全相等記於 equal_pairs，不建立任一方向的邊。
每種排序的「已建立邊＋相等配對＋人工待辦」必須剛好覆蓋所有不同物件配對。

## 草稿與人工處理

每個待辦包含 view_id、物件配對、關係種類與原因；相機後方案例另記 camera_regions。
沒有 unresolved 邊；已算出的邊皆為 accepted，有待辦的圖標為 needs_review。
完整圖為 complete，兩者都放入 graphs，並保存 review_task_count。人工清單是本版交付的處理入口，尚未實作人工決定的匯入器；
不可把草稿直接改名當作正式 GT。

## HTML 檢查器

直接用瀏覽器開啟本次輸出的 `inspect.html`，可切換全部所選視角，保留既有多選類型、
關係篩選、縮放、證據明細與 JSON 匯出。草稿的選單項目與狀態列均有標示。
點選節點可看 position、相機座標、投影、距離、AABB 及可見性；不可見節點使用橘色虛線外框。
「人工待辦」依當前物件與關係篩選；即使目前篩選沒有待辦，狀態列仍顯示整張圖尚未完成。
篩選結果匯出保留 source_graph_status 與待辦，不能被誤認為完整正式圖。

也可以重新建立檢查器：

```sh
python3 inspect_graph.py \
  --run-dir outputs/ground_truth/20261105T120357_736949Z/full-unified-v1
```

新格式預設載入所有視角，`--complete-only` 只載入完成圖。
舊版 full/drafts 目錄仍可讀取，舊版草稿需加 `--include-drafts`。
HTML 為本次輸出的靜態快照，更新圖後需要重新產生。

## 場景驗收：20261105T120357_736949Z

| 視角 | 節點 | on | inside | 左右 | 遠近 | 總邊數 | 左右待辦 | 狀態 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| view_1 | 77 | 26 | 12 | 1889 | 2926 | 4853 | 1035 | 草稿 |
| view_2 | 77 | 26 | 12 | 2344 | 2926 | 5308 | 580 | 草稿 |
| view_3 | 77 | 26 | 12 | 2924 | 2926 | 5888 | 0 | 完成 |
| view_4 | 77 | 26 | 12 | 2848 | 2926 | 5812 | 76 | 草稿 |

每個視角都有兩對相等水平投影，沒有相等距離。view_1、view_2、view_4 分別有
15、8、1 個物件中心位於相機後方；每個相關配對列為一筆待辦，不是遺漏節點。

```sh
python3 -m unittest discover -s tests -p 'test_full_ground_truth.py' -v
```

測試包含旋轉、平移、俯仰、相機平面、畫面外物件、AABB 診斷、相等值、極小差距、
不可見物件、逐視角發布、草稿讀取、輸入錯誤及四視角的實際數量。
