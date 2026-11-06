> 目前入口為 `python3 -m reasoning`，實際新輸出位置見 [操作指南](operation_guide.md#6-模型推理)。下方歷史案例的產物相對路徑指 legacy/ 原始紀錄。

# Ollama 操作、互動與修正說明

本文件合併原 instruction 與 interaction。快速開始見 [README](../README.md)，模組呼叫見 [架構](architecture.md)，欄位規格見 [輸出格式](output_format.md)，研究 prompts 見 [研究設計](research_design.md)。

## 1. 如何呼叫、如何隔離

`reasoning/pipeline.py` 透過 `reasoning/ollama_client.py` 呼叫 `POST http://localhost:11434/api/chat`，預設模型為 `gemma4:e4b`，使用 `stream=false` 等待完整回應。

| 任務 | 模型輸入 |
| --- | --- |
| `view_1`～`view_4`，依序獨立執行 | 相同英文模板、自己的視角 ID 與圖片，不含其他 view 的觀察或相機姿態。 |
| `correspondence` | 四份觀察文字與篩選後的相機資訊，不附圖。 |
| `scene_graph` | 四份觀察、已通過的對應、相機資訊、關係規則與節點／來源對照，不附圖。 |

每次重新建立 `messages`。首次使用 `system: 共通規則`、`user: 任務及資料`；修正時再加 `assistant: 同任務上一份待修正回答`、`user: 錯誤與修正要求`。每次保留原始任務，僅附上一稿，不累積全部歷史。階段 1 修正仍附自己的原圖；階段 3 若已正規化，修正輸入使用該版本。

`keep_alive="10m"` 控制模型載入時間，對話內容仍由本次 `messages` 決定。中央模型看到四份觀察，是程式明確傳入的資料，不是四個 view 共用聊天紀錄。`objects.json/.csv` 與真值物件總數不進入 prompt。

## 2. 階段與嘗試次數

三個建圖階段是既定流程；`_01`、`_02` 等是同一任務的呼叫編號。程式自動檢查，通過就停止；未通過才在預算內要求修正。

```text
全新任務最多呼叫次數 = 1 次首次生成 + --format-retries
```

| 設定 | 最多呼叫 | 行為 |
| --- | --- | --- |
| `--format-retries 0` | 1 次 | 仍正規化與驗證，但不要求模型修正。 |
| `--format-retries 2` | 3 次 | 最多首次生成加兩次修正。 |
| `--format-retries 3`（預設） | 4 次 | 通過即停，不必跑滿。 |
| `--format-retries 5` | 6 次 | 增加預算，不保證成功。 |

六個任務各自計算：完整新 run 一次全通過是六次推論；預設預算下，六者都在最後一稿通過則是 24 次。服務查詢不算推論。續跑編號延續歷史，預算對本次執行生效；重用或 fork 恢復可減少新呼叫。

## 3. 修正原因與停止條件

驗證器檢查格式，也檢查 ID、對應、來源與狀態。例如 `g7a` 不是合法全域 ID；同視角的分開物件不能直接確定合併；三元組端點須符合來源；frame 必須是 `physical` 或適當的 `view_N`。

每次先保存原始回答，圖再經 `normalize_graph()` 正規化，最後嚴格驗證。來源可唯一確定的 frame 別名與同參考系的重複邊，由程式處理並留紀錄；剩餘錯誤才要求模型修正。原始回答不覆寫。

修正耗盡、相同無效回答與錯誤重複、HTTP 失敗或回答空白／截斷時會停止。中央修正使用既有文字資料，不是回看原圖的定向查證；目前尚未執行研究階段 4–5。

## 4. 操作參數與恢復

在專案根目錄執行；`RUN_DIRECTORY` 請替換為先前顯示的輸出目錄。

```sh
# 指定最多兩次修正：
python -m reasoning --scene-dir data/scenes/sample/FloorPlan1/20261105T120357_736949Z/basic --format-retries 2
# 只檢查資料、輸出 prompt，不連線 Ollama：
python -m reasoning --scene-dir data/scenes/sample/FloorPlan1/20261105T120357_736949Z/basic --dry-run
# 沿用同一程式與設定繼續：
python -m reasoning --scene-dir data/scenes/sample/FloorPlan1/20261105T120357_736949Z/basic --resume RUN_DIRECTORY
# 程式修正後，建立新 run 並重用舊結果；需沿用來源生成設定：
python -m reasoning --scene-dir data/scenes/sample/FloorPlan1/20261105T120357_736949Z/basic --fork-from RUN_DIRECTORY --stage 3 --thinking on
```

| 參數 | 預設與用途 |
| --- | --- |
| `--scene-dir` | 必填，含四張圖片與 `views.json` 的目錄。 |
| `--stage` | `all`；可選 `1`、`2`、`3`。後兩者須有已通過的前置結果，搭配 resume 或 fork。更改階段順序需修改程式。 |
| `--model`、`--ollama-url` | `gemma4:e4b`、`http://localhost:11434`。 |
| `--output-dir` | `data/runs/`，每個新實驗位於 exp_<UTC>/<scene>/；可用 --experiment-id 命名。 |
| `--timeout`、`--format-retries` | 每次 HTTP 請求 600 秒；每任務最多修正 3 次。 |
| `--num-ctx`、`--num-predict` | 上下文 32768、最大輸出 8192 tokens，依記憶體調整。 |
| `--temperature`、`--seed` | `0.2`、`42`，不保證跨硬體／版本逐字重現。 |
| `--thinking` | `auto`：支援時僅中央文字任務啟用推論；另可選 `on`、`off`。 |
| `--verification-budget` | 最多提出 4 個查證問題，只保存、不執行。 |

`--resume` 核對輸入、程式、模型 digest、生成設定與完成檔案雜湊。程式改版可用 `--fork-from`，在新目錄重新驗證並複製階段 1–2，保留來源 run；舊圖回答若重驗通過便不需新推論，否則只修正圖。兩者互斥，且不能搭配 dry-run；dry-run 目錄不能續跑推論。即使全部重用，推論流程仍會查詢 Ollama 服務與模型。

變更 token 或其他生成設定應開新 run；只增加修正預算可以續跑。若強制終止留下 `.run.lock`，確認無程序使用該目錄後才移除。

## 5. 輸入與結果位置

以下路徑相對於 `data/runs/<exp_id>/<scene_id>/`；`TASK` 為上述六個任務名稱，`NN` 為嘗試編號。

| 位置 | 內容 |
| --- | --- |
| `prompts/TASK_NN.txt` | 本次文字輸入，修正時包含上一稿與錯誤。 |
| `responses/TASK_NN.md/.json` | 原始回答／完整 API 回應，JSON 另含用量及回傳的 thinking。 |
| `observations/view_N.md` | 通過檢查的局部觀察。 |
| `correspondence.md`、`scene_graph.md` | 通過檢查後採用的對應與圖。 |
| `camera_metadata.json` | 送入中央模型的相機白名單。 |
| `responses/*.normalized.md`、`normalizations/*.json` | 正規化草稿、修正與合併紀錄、前後雜湊。 |
| `run_manifest.json`、`validation_report.json` | 設定、雜湊、歷史嘗試與用量／各任務最新檢查結果。 |

原圖留在 `--scene-dir`，呼叫時編為 base64，不複製到 run。`prompts/*.txt` 也不含圖片或完整 HTTP JSON；重建輸入需搭配原圖、manifest 及 client 的角色組裝方式。

## 6. 實測：首次生成加兩次修正

歷史案例已搬到 `data/runs/sample/exp_20261021T162018_966707Z/unidentified_scene/legacy/`，使用 `thinking=on`。四個 view 各一次，加下列六次中央呼叫，共十次推論。

| 嘗試 | 物件對應 | 建圖 |
| --- | --- | --- |
| 01 | 把同視角的 `v3_o3`、`v3_o8`、`v3_o9` 確定合併為 `g7`，失敗。 | `e5` 的端點與來源反向，失敗。20 條原始邊另有重複，合併後為 19 條。 |
| 02 | 拆成 `g7a`～`g7d`，但 ID 格式不合法。 | 只改 `e5` 的解釋，結構未改，仍失敗。 |
| 03 | 改為 `g22`～`g25` 並同步引用，通過：24 個全域節點、40 筆對應、3 項歧義。 | 移除 `e5` 後通過：24 個節點、18 條邊、4 項未解問題、4 個查證請求。 |

原始 `v1_r5` 是「門在中島右側」，端點為 `g3 → g1`；模型改寫為 `(g1, image_left_of, g3)`。一般方向邏輯可等價改寫，但目前 baseline 禁止反向推導，驗證器要求同序來源，因此拒絕。第三稿移除這條邊，並未查證它為假。

重複邊 `e20` 合併到 `e17`，保留來源 `v3_r2, v4_r5`。原始稿、正規化稿與每次錯誤皆可從 [manifest](../data/runs/sample/exp_20261021T162018_966707Z/unidentified_scene/legacy/run_manifest.json) 及同編號 `prompts/`、`responses/` 追查；正式結果為 [物件對應](../data/runs/sample/exp_20261021T162018_966707Z/unidentified_scene/legacy/correspondence.md) 與 [scene graph](../data/runs/sample/exp_20261021T162018_966707Z/unidentified_scene/legacy/scene_graph.md)。

**通過結構檢查可能伴隨關係遺漏，不等於準確率提升。** 完整評估還需獨立衡量辨識、對應、關係正確率及覆蓋率。原始 run 是 Git 忽略的本機產物，本節保留關鍵摘要。
