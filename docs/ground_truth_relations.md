# Ground-truth 場景圖的關係定義

可修改定義存放於根目錄 `relation_definitions.json`，版本為
`physical-and-view-relations-v1`。本次完成定義，分類及匯出程式尚未接入此設定。

## 四種關係

每條 edge 的 relation 為下列其中一個值，統一使用小寫名稱。
同一對物件可以有多條 edge，每種關係及每個視角分開記錄。

| 關係 | 方向與定義 | 參考系 |
| --- | --- | --- |
| `on` | source 由 target 的表面接觸並支撐；須有支撐重力的證據 | `physical` |
| `inside` | source 完整位於 target 的內部空間；部分包含保留不確定 | `physical` |
| `image_left_of` | source 的可見分割像素中心 X 小於 target，且差距超過門檻 | 指定 view ID |
| `closer_to_camera` | source 可見表面的深度中位數小於 target，且差距超過門檻 | 指定 view ID |

`on` 與 `inside` 可同時成立，例如物件被容器底部支撐，也完整位於容器內。
每條關係都需要自己的證據，不能由其中一條自動推得另一條。

## 範圍與候選配對

- 節點僅包含 `visible_objects.json` 內的物件，完整 metadata 從 `objects.json` 回查。
- 每條邊的兩端都必須是節點；不可見父容器不新增為節點。
- 可見性只決定納入範圍，不代表任何關係成立。
- `on`、`inside` 可由 `parentReceptacles`、容器類型及幾何資訊提出候選，不能直接接受為真值。
- 左右、遠近比較每個視角中共同可見的不同物件，不受 `parentReceptacles` 限制。
- 左右、遠近必須逐視角記錄；不同視角的相反關係不構成衝突。
- 不建立自身關係，不自動使用遞移或反向推論。

## 判定方式

### on / inside

`on` 需要實際支撐面的接觸與支撐證據；Shelf 整體 AABB 的最高點不一定是支撐面。
`inside` 需要完整位於容器內部空間的證據；容器 AABB 不等於內部空間。
對開口容器，完整包含以定義好的內部空間為準，物件突出開口時保留不確定。
具體接觸、支撐面與內部空間資料的取得方式留待實作設計；資料不足時標為 unresolved。

取消「可見就預設 ON」及「Shelf、Floor 等類型一律 IN」的最終分類規則。
類型只提供候選提示。Bottle 與 Hand Statue 的 `on Shelf` 可作待驗證候選，
不能僅憑類型自動接受為 `inside Shelf`。

### image_left_of

同一 view 中，分別計算兩物件非零 instance-mask 像素的 **X 座標平均值**，
再除以圖片寬度。中心採可見像素質心，不是 bounding box 中點或完整物件中心。
若 `target_x - source_x > min_horizontal_gap_ratio`，接受 source 在 target 左側。
若相反方向差距超過門檻，以相反方向建立邊；差距不足或等於門檻時保留不確定。
遮擋可能改變質心，這是此影像關係定義的一部分。

### closer_to_camera

對每個物件可見遮罩中的有效深度像素（有限、正值）取中位數。
若 `target_depth - source_depth > min_depth_gap_m`，接受 source 更靠近相機。
若相反方向差距超過門檻，以相反方向建立邊；差距不足或等於門檻時保留不確定。
採相機軸向深度，單位為公尺；此數值代表可見表面深度，不是物件位置至相機的距離。
深度與遮罩必須來自同一次拍攝、相同相機及對齊的像素座標；實作前需核對深度格式並轉換。
缺少遮罩或有效深度時保留不確定。

## 可修改設定

JSON 的 relations 中，每種關係有 enabled、定義、參考系及判定要求；
影像與深度關係另外有 parameters。

| 參數 | 初始可調值 | 含義 |
| --- | --- | --- |
| `min_horizontal_gap_ratio` | 0.01 | 超過圖片寬度 1% 的左右差距 |
| `min_depth_gap_m` | 0.03 | 超過 3 公分的深度差距 |

數值是初始設定，尚未以資料校準。變更語意或門檻時更新版本；未來匯出程式應保存
實際設定快照，既有結果不隨設定修改而改變。新增關係名稱時，仍需對應計算與驗證方法。

## Edge 格式與不確定性

必要欄位：source、relation、target、frame、status、evidence、definition_version。

- relation：四種關係之一；一條 edge 只記錄一種。
- frame：物理關係為 physical，視角關係為實際視角 ID，例如 view_3。
- status：accepted、unresolved 或 conflicting。
- evidence：判定方法、測量值及來源，供檢查或重新分類。

UNKNOWN 不作第五種空間關係。候選關係缺乏證據時標為 unresolved；若連候選關係也
無法確定，放入未解決事項，不臆造 on 邊。缺少邊不代表已證明關係為假。

## 原有定義及舊輸出

`scene_prompts.py` 的 RELATIONS 保留原始四種語意定義，供模型流程與版本比較參考。
本文件補上 ground-truth 測量約定，不將真值資料送入模型建圖提示。

先前的 `ground_truth_relations.py` 和已產生的 `ground_truth_scene_graph.json`
使用 visible-parent-type-v1，只產生類型覆寫的 ON/IN。
它們是舊版試作，**不符合這份完整定義，不能當作新版評分真值**。
後續實作需接入新設定、補足四種關係判定及必要的拍攝資料，再重新產生場景圖。
