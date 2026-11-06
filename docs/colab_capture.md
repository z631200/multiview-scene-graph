# Colab 場景資料匯出

Notebook 自行完成拍攝與資料匯出，不需額外上傳 Python 檔案。
預設 4 個 1600×1600 一般視角，可選擇 3 個。此階段只保存資料，不計算場景圖關係。
VLM 後續僅讀取照片；Metadata、遮罩及深度供另外的 ground-truth 計算使用。

也可使用 [本機 CLI](local_capture.md) 產生相同的 `capture-v2` 格式，直接保存於本機目錄。

## 檔案格式

| 檔案 | 內容 |
| --- | --- |
| view_01.png ～ view_04.png | 各視角 RGB 照片 |
| depth_01.npy 等 | 同一視角的原始 float32 深度陣列，單位公尺 |
| instance_masks_01.npz 等 | 可見 Metadata 物件的布林遮罩，以及 Unicode object_ids 陣列 |
| segmentation_mapping_01.json 等 | objectId、NPZ 遮罩 key、像素數、objectId 到 RGB 顏色對應 |
| instance_segmentation_v01.png 等 | 原始 instance segmentation 彩色圖 |
| metadata_01.json 等 | 該次拍攝的完整原始 event.metadata，包含所有物件及原生 visible |
| objects.json | 全部物件最近一次拍攝 Metadata，及跨視角 visible / visible_views；原生 visible 另存 ai2thor_visible |
| visible_objects.json | 可見聯集；欄位為 objectId、objectType、name、position、rotation、visible_views |
| views.json | schema_version=capture-v2；每視角檔案路徑、像素數、圖片尺寸與相機資訊 |
| objects.csv | 原有全部物件座標、旋轉資料 |
| reachable_positions.json、viewpoints.png | 可達位置、拍攝位置圖 |
| view_00.png | 俯視參考圖，僅供觀看，不納入可見性或後續計算 |

一般視角的 RGB、遮罩、深度、分割圖及 Metadata 均取自同一個成功的 Teleport event。
陣列索引為 [row_y, column_x]，原點在左上角，尺寸與 RGB 一致。
每個 NPZ 的 object_ids 順序對應 mask_0000、mask_0001 等；也可由 JSON 對應表讀取。
空視角會儲存空的 object_ids 陣列，不生成假的物件遮罩。
未包含在物件 Metadata 的渲染區域仍可出現在分割圖，但不列為場景物件。

## 深度與相機

Controller 明確使用 renderDepthImage=True、depth_format=DepthFormat.Meters。
儲存 event.depth_frame 原始數值，不轉換為視覺化圖片或其他距離定義。
depth_info 記錄單位、來源、有效性統計及相機近遠裁切面；裁切範圍外的幾何不能由深度圖復原。
非有限值與非正值原樣保存；後續計算需依需求排除，不能拿來判定物件遠近。
此匯出階段不加入左右差距或深度差距門檻。

相機資訊包含 cameraPosition、agent.rotation、cameraHorizon（正值向下）、垂直 FOV 與圖片寬高。
這些資料可供之後把物件世界座標轉到各視角；保留原始 Metadata 方便核對。
AI2-THOR 版本記於 views.json。深度保持該版本的原生定義，沒有假定為物件中心的歐氏距離。

參考：[官方 Event 與影像格式](https://ai2thor.allenai.org/ithor/documentation/environment-state/)、
[深度格式轉換原始碼](https://github.com/allenai/ai2thor/blob/main/ai2thor/server.py)。

## 讀取範例

~~~python
import json
from pathlib import Path
import numpy as np

scene_dir = Path('場景輸出目錄')
manifest = json.loads((scene_dir / 'views.json').read_text(encoding='utf-8'))
view = manifest['views'][0]
depth = np.load(scene_dir / view['depth'], allow_pickle=False)
mapping = json.loads((scene_dir / view['segmentation_mapping']).read_text(encoding='utf-8'))
with np.load(scene_dir / view['instance_masks'], allow_pickle=False) as archive:
    for item in mapping['masks']:
        object_id = item['objectId']
        mask = archive[item['key']]
        object_depth_pixels = depth[mask]
~~~

## 重跑與下載

從 Workspace 開始依序重跑，新的 Controller 才會啟用深度。舊資料不能重建未儲存的深度。
重跑拍攝先刪除舊完成清單 views.json，全部成功後才建立新清單。
下載前核對清單與所有必要檔案；中途失敗或缺少深度等檔案時拒絕下載。
ZIP 僅包含本次清單指定的視角資料、彙總資料及參考圖，不帶入舊視角或舊場景圖。
俯視圖不加入 views.json 的一般視角清單，也不影響物件可見性。

## 離線驗證

~~~sh
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
~~~

測試使用 NumPy 小型陣列檢查資料還原、視角對應及失敗情況，不需 AI2-THOR 或 Colab。
實際 Unity 渲染仍需在可用的 AI2-THOR 環境執行 Notebook 或本機 CLI 驗證。
