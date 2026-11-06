# 本機擷取 AI2-THOR 場景

[scene_capture/local/capture.py](../scene_capture/local/capture.py) 將目前
[Colab Notebook](../scene_capture/colab/AI2_THOR_Scene_Capture.ipynb) 的拍攝流程移到本機 CLI。
預設 `FloorPlan1`、4 個不同位置、1600×1600、水平朝向房間中央，另外儲存
`view_00.png` 俯視參考圖與 `viewpoints.png` 位置圖。可選 3 個一般視角。
可見性仍以每視角至少 1 個 instance mask 像素判定；俯視圖不參與計算。

輸出沿用 `capture-v2`，包含 RGB、原始公尺深度、布林遮罩、分割圖片及對應表、
完整原始 Metadata、全部物件與跨視角可見聯集。欄位與讀取方式見
[場景資料匯出格式](colab_capture.md)。本機版不需要 `ai2thor-colab`、Google Drive
或 Colab 下載功能；原 Notebook 仍可獨立使用。

## 安裝與執行

以下從專案根目錄操作，使用 Python 3.10+；建議為模擬器建立獨立的 Python 3.10／3.12
環境。只有查看 `--help` 不需安裝套件。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-capture.txt
python -m scene_capture.local --help
```

依賴包含 `ai2thor==5.0.0`、NumPy、Pillow、Matplotlib；模擬器版本與既有
`scene_capture/demo/requirements.txt` 一致。Colab 使用 `--upgrade ai2thor`，兩邊可能安裝不同版本；
格式相同不代表不同模擬器版本的渲染或場景內容完全相同，實際版本會記在 `views.json`。

若在 Linux 圖形桌面終端機執行：

```sh
python -m scene_capture.local --output-dir data/scenes/FloorPlan1/capture_001/basic
```

Linux SSH／無視窗環境可指定 CloudRendering：

```sh
python -m scene_capture.local --headless --output-dir data/scenes/FloorPlan1/capture_001/basic
```

`--headless` 在本機離屏渲染，不需要 X11，但需要可用的 Vulkan loader 與 GPU 驅動。
官方用法見 [Headless Setup](https://ai2thor.allenai.org/ithor/documentation/)，
loader 檢查見 [官方平台實作](https://github.com/allenai/ai2thor/blob/main/ai2thor/platform.py)。
一般 Linux 模式則需要可存取、支援 GLX、24-bit 色深且寬高足以容納照片的 X11 螢幕。
本機版沿用 AI2-THOR 的顯示檢查，不會自動安裝系統套件或修改桌面授權。
其他作業系統需先確認所用 AI2-THOR 版本與硬體支援；`--headless`、`--display` 限 Linux。

首次啟動 Controller 會下載 Unity 場景至 `~/.ai2thor`，需網路與該目錄寫入權限；
參見 [官方 First Steps](https://ai2thor.allenai.org/ithor/documentation/)。

## 參數與儲存

| 參數 | 預設值 | 用途 |
| --- | --- | --- |
| `--config` | 無 | 可讀取 configs/capture.yaml，CLI 明確值優先 |
| `--scene` | `FloorPlan1` | AI2-THOR 場景名稱 |
| `--num-views` | `4` | `3` 或 `4` 個一般視角 |
| `--image-size` | `1600` | 正方形照片邊長，可選 `400`、`600`、`800`、`1600` |
| `--horizon` | `0` | 俯仰角，範圍 -30～60 度，正值向下 |
| `--output-dir` | `data/scenes/<scene>/<UTC capture_id>/basic` | 新的場景目錄；拒絕覆寫既有目錄 |
| `--headless` | 關閉 | Linux Vulkan CloudRendering |
| `--display` | 繼承 `DISPLAY` | 指定 Linux X11 display；與 `--headless` 互斥 |
| `--timeout` | `300` | Unity 啟動與每個 action 的 timeout 秒數 |
| `--zip` | 關閉 | 額外產生 `<輸出目錄>.zip`，也保留原資料夾 |

例如先用較小照片確認環境，再用新目錄產生正式資料：

```sh
python -m scene_capture.local --headless --image-size 600 --output-dir data/scenes/FloorPlan1/check_001/basic
python -m scene_capture.local --headless --scene FloorPlan1 --image-size 1600 \
  --output-dir data/scenes/FloorPlan1/capture_002/basic --zip
```

選點規則與 Notebook 相同：取得可到達位置，在 XZ 外接矩形四角附近選擇不同位置，
朝向矩形中央；Teleport 失敗則試下一個候選點。此規則不能保證每張照片看見所有物件。

每次執行建立新目錄；所有一般視角、俯視圖和位置圖成功後，才寫入 `views.json`
完成清單。中途失敗可能留下部分檔案，但不會標記為完成或產生 ZIP；請修正原因後
使用新目錄重跑。Controller 建立成功後，無論拍攝完成、失敗或中斷都會嘗試停止。
ZIP 僅包含本次清單的資料與參考圖，不帶入額外檔案。

## 接續建圖與 GT

本機產生的資料夾可直接傳給現有程式，不需搬到 `data/scenes/<scene>/<capture_id>/basic`：

```sh
# 建圖流程仍要求四個一般視角；先離線確認輸入。
python -m reasoning --scene-dir data/scenes/FloorPlan1/capture_002/basic --dry-run
# 使用本機 Ollama 建圖。
python -m reasoning --scene-dir data/scenes/FloorPlan1/capture_002/basic
# GT 直接讀取相同目錄；也支援三視角擷取。
python -m gt.visible --scene-dir data/scenes/FloorPlan1/capture_002/basic
python -m gt.full --scene-dir data/scenes/FloorPlan1/capture_002/basic
```

## 排錯與驗證範圍

找不到 Python 套件時，確認安裝與執行使用同一個環境。X11 授權或尺寸錯誤時，
從圖形桌面的使用者終端機執行、選擇可容納的 `--image-size 600`，或在具備 Vulkan
的 Linux 使用 `--headless`。提高 timeout 無法修復顯示授權或螢幕尺寸。
Vulkan 初始化失敗時，先檢查 GPU 驅動與 `vulkaninfo --summary`；相關說明也見
[本機任務的 Linux 排錯](../docs/demo.md#linux-顯示環境排錯)。

Unity 日誌通常位於 `~/.ai2thor/log/unity.log` 或
`~/.config/unity3d/Allen Institute for Artificial Intelligence/AI2-THOR/Player.log`。

```sh
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
```

離線測試用假的 Controller 與真實 NumPy／PNG／位置圖匯出，逐項比對目前 Notebook
的 3／4 視角資料，並讓產物通過建圖輸入讀取與兩種 GT 生成器。另檢查失敗時不建立
完成清單、ZIP 完整性與 Controller 釋放。這些測試不執行 Unity；目前執行環境未安裝
AI2-THOR，且 NVIDIA 驅動無法由 `nvidia-smi` 存取，尚未完成真實渲染驗證。
