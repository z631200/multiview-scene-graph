# 本機 AI2-THOR 任務示範

本目錄是獨立的模擬器任務流程。根目錄的多視角建圖說明見 [專案 README](../README.md)，兩者的關係見 [架構文件](../docs/architecture.md)。所有指令均從專案根目錄執行，使用 `python3 -m scene_capture.demo`。

以 AI2-THOR 場景 metadata 評估任務目標的 Python 原型。目前提供一個固定 `FloorPlan1` 示範：取得刀具、切馬鈴薯、裝碗、微波加熱，再將碗放回檯面。動作計畫是手寫腳本，尚未包含自動規劃器、多場景評測、成功率統計或完整 ALFRED benchmark。

**無法執行 AI2-THOR 的電腦仍可閱讀程式、查看 CLI 說明、修改目標並執行離線測試。** 場景路徑、互動效果與錄影須在可執行 AI2-THOR 的環境驗證。

## 專案結構

```text
main.py                  CLI、執行動作計畫、釋放 controller
demo_task.py             固定任務、PDDL 目標與 ACTION_PLAN
task_definition.py       任務資料與目標設定
robot_interface.py       動作轉譯、可見物件選取與中間幀回呼
simulation_platform.py   載入場景、逐步評估、JSON 紀錄與選用錄影
benchmark_referee.py     任務成功判定與動作回饋
pddl_goal.py             PDDL 目標子集合解析器與 metadata evaluator
requirements.txt         執行所需直接依賴
tests/test_offline.py     不需模擬器的回歸測試
data/runs/sample/demo_legacy/FloorPlan1/demo/         舊動作草稿、影片、紀錄與套件清單
outputs/                 新執行產物（Git 忽略）
```

## 離線開發與驗證

在 `scene_capture/demo/` 目錄使用可用的 Python 3 執行；整理時以 Python 3.12.7 驗證。不需安裝 `requirements.txt`。

```sh
python3 -S -m unittest discover -s tests -p test_demo.py -v
python3 -S -m scene_capture.demo --help
python3 -m compileall -q scene_capture/demo tests/test_demo.py
```

`-S` 不載入 site-packages，驗證離線路徑只使用標準函式庫。測試使用假的 controller 與人工 metadata，不會載入 Unity 或下載場景。它們涵蓋目標判定、舊 API 相容性、動作參數、紀錄、資源釋放與成功後追加步數；不能證明真實場景中的任務可完成。

若 Windows 的 `python` 指向 Microsoft Store 佔位程式，請改用已安裝 Python 的完整路徑。

## 在支援 AI2-THOR 的電腦執行

以下步驟供另一台具備 AI2-THOR 執行環境的電腦使用。安裝 Python 套件並不等於 Unity 場景一定能啟動；本專案未驗證目前各作業系統、顯示或 GPU 設定的相容性。

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python3 -m pip install -r scene_capture/demo/requirements.txt
python3 -m scene_capture.demo
```

直接依賴保留原專案版本：`ai2thor==5.0.0`、`opencv-python==4.12.0.88`。其餘依賴由 pip 解析；這份檔案不是完整鎖定檔。原本完整套件清單另存於 `data/runs/sample/demo_legacy/FloorPlan1/demo/requirements.txt`，此次沒有升級套件版本。

可選參數：

```sh
python3 -m scene_capture.demo --no-video --step-delay 0 --output-dir data/runs/demo_trial_001/FloorPlan1/demo
```

| 參數 | 預設值 | 用途 |
| --- | --- | --- |
| `--output-dir` | `outputs` | JSON 紀錄及影片的輸出目錄 |
| `--no-video` | 關閉 | 指定後停用錄影，也不會匯入 OpenCV |
| `--headless` | 關閉 | Linux 使用 CloudRendering，免 X11，但需要可用的 Vulkan 驅動 |
| `--step-delay` | `2.0` | 每個高階動作之間的等待秒數，須為有限非負數 |

輸出包含 `trace_log.json`，以及啟用錄影時的 `run.mp4`（600 × 600，設定 8 FPS，`mp4v`）。重用同一目錄會覆寫同名檔案；不同實驗請指定不同目錄。JSON 記錄 step、timestamp、action、target、success、error_message、referee_feedback、goal_status；不含完整 observation 或場景 metadata。

首次達成目標後最多繼續執行三個計畫動作，或至計畫結束。單一動作失敗會記錄並繼續，不會自動重新規劃。結束或拋出例外時會嘗試儲存紀錄、釋放影片並停止 controller。

## Linux 顯示環境排錯

若初始化出現 `Authorization required`、`Can't connect to display ":0"` 與
`No valid X display found`，代表預設 Linux64 後端找不到可存取、具 GLX 的 X11
顯示環境。此時尚未執行任務；授權錯誤也不代表機器上完全沒有 X server。

若透過 SSH 或不需要顯示視窗，可以使用官方的
[CloudRendering 模式](https://ai2thor.allenai.org/ithor/documentation/)：

```sh
python3 -m scene_capture.demo --headless
# 若同時不需要儲存影片：
python3 -m scene_capture.demo --headless --no-video
```

CloudRendering 在本機離屏渲染，不需要 X11；仍需要 Linux 與可用的 Vulkan
驅動，不是免 GPU 的模式。`--no-video` 只停用影片寫入，單獨使用無法解決 X11 問題。
若尚未配置 Vulkan，可在 Ubuntu 由有管理權限的人安裝檢查工具與 loader：

```sh
sudo apt-get install libvulkan1 vulkan-tools
vulkaninfo --summary
```

確認能列出預期使用的 GPU；安裝 loader 不會自動修復 GPU 驅動。如果仍出現
Vulkan 初始化錯誤，需檢查該機器的 GPU 驅動；容器環境也需確認 GPU 存取設定。
官方維護者的[無 Xorg 執行說明](https://github.com/allenai/ai2thor/issues/924)
亦列出 `libvulkan1` 需求。

若需要顯示 Unity 視窗，先在登入圖形桌面的同一使用者終端機執行：

```sh
printf 'DISPLAY=%s\nXAUTHORITY=%s\n' "$DISPLAY" "$XAUTHORITY"
python3 -m scene_capture.demo
```

保留桌面工作階段提供的 DISPLAY 與授權設定，不要假設顯示編號一定是 `:0`。
SSH、切換使用者或 sudo 啟動的程序可能沒有該桌面的 X11 授權；
優先從原桌面使用者終端機執行，或改用 `--headless`。本專案不會自動變更系統顯示授權。

## 定義任務與目標

修改 `demo_task.py` 的 `build_task()`、`GOAL_PDDL` 與 `ACTION_PLAN` 可調整示範。動作路徑只針對目前的 `FloorPlan1`；單純改 scene ID 不代表路徑仍然適用。

```python
from scene_capture.demo.task_definition import TaskDefinition
from scene_capture.demo.benchmark_referee import Referee

task = TaskDefinition("cooked_potato", "FloorPlan1", "Cook a potato")
task.set_goal_pddl("""
(:goal
    (exists (?o # object)
        (and (objectType ?o PotatoSlicedType) (isCooked ?o True))))
""")
result = Referee().check_success(task, {"objects": [
    {"objectId": "PotatoSliced|example", "objectType": "PotatoSliced", "isCooked": True}
]})
assert result["is_success"]
```

解析器支援 `and`、`not`、`exists`、`forall`，以及 `opened`、`inReceptacle`、`objectType`、`receptacleType` 和一般 metadata 屬性比較。量詞使用此專案的 `(?o # object)` / `(?r # receptacle)` 語法；不是完整標準 PDDL 實作，不提供規劃搜尋。`receptacle` 範圍包含標記為 receptacle 或 openable 的物件。`inReceptacle` 保留既有 ID 子字串比對，並非嚴格關係推論。

預設目標保留原有語意：所有可開啟的容器關閉、至少一個碗在檯面上、至少一片煮熟的馬鈴薯在某個碗內。**後兩個存在量詞各自綁定碗，可能是不同的碗；也不要求每片馬鈴薯都煮熟，或微波爐已關閉。** 若需要更嚴格的評分，應修改目標並新增 metadata 測試。

`TaskDefinition.add_goal(object_type, property_name, expected_value)` 舊 API 仍保留。同類型的所有條件必須由同一物件滿足；設定 PDDL 時優先使用 PDDL。完全沒有目標時回傳失敗。

## 動作介面

`SimulationPlatform.load_task(task)` 依任務設定重設場景，之後呼叫 `run_step(action, target)`，回傳 `image`、`feedback`、`task_done`、`goal_details`。若直接建立平台，使用者負責呼叫 `finish()` 與 `controller.stop()`；CLI 已處理這些生命週期。

| 動作 | target |
| --- | --- |
| `MoveAhead`、`MoveBack` | 距離，預設 0.25 |
| `RotateLeft`、`RotateRight` | 角度，預設 90，分段執行 |
| `LookUp`、`LookDown` | 角度，預設 30，分段執行 |
| `Teleport` | 包含 `x`、`y`、`z` 的座標字典 |
| `OpenObject`、`CloseObject`、`PickupObject`、`ToggleObjectOn`、`ToggleObjectOff`、`SliceObject` | objectId 或 objectType；未給 target 時嘗試畫面中心 |
| `PutObject` | 容器 ID / 類型、`"center"`、`{"x": 0.5, "y": 0.5}`；`None` 表示放落手中物件 |
| `ShowDetail` | objectType，列印 metadata |
| `Wait` | 實際等待秒數，預設 1；重複記錄當前影格，不推進模擬器物理步驟 |
| `Stand`、`Done` | 無 |

objectType 比對不分大小寫，從可見且符合動作能力的候選選取；有 screenPosition 時偏向畫面中心，否則使用 agent 距離。直接傳入 objectId 時交由模擬器檢查。動作成功與任務成功是兩個不同判定。

## 維護與遷移紀錄

- 原入口內的任務與動作清單移至 `demo_task.py`；移除未呼叫的環境修改函式與註解掉的動作。
- 移除通用介面內的固定場景 Teleport 名稱捷徑。請改傳座標字典。
- `PutObject` 使用原本優先採用的 `objectId` 參數，移除遇到任意例外便重試舊參數的相容分支。
- 移除未使用匯入；AI2-THOR 延後至實際執行時匯入，OpenCV 延後至錄影時匯入。
- 修正空目標誤判成功、Wait 繼承前一步失敗、ToggleObjectOff 未篩選能力、成功後追加步數少算一步，以及例外時未停止 controller。
- 原始 `action_plan.txt`、`run.mp4`、`trace_log.json` 原樣移至 `data/runs/sample/demo_legacy/FloorPlan1/demo/`，不當作目前程式輸入；新產物預設輸出至 Git 忽略的 `data/runs/demo_<UTC>/FloorPlan1/demo/`。
