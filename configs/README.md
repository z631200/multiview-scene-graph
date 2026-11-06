# 設定檔

從專案根目錄執行。設定鍵名對應 CLI 的底線名稱；明確的 CLI 參數優先。

```sh
python3 -m scene_capture.local --config configs/capture.yaml --scene FloorPlan1 --headless
python3 -m gt.visible --config configs/gt.yaml --scene-dir <capture/basic> --gt-id gt_example
python3 -m gt.full --config configs/gt.yaml --scene-dir <capture/basic> --gt-id gt_example
python3 -m reasoning --config configs/experiments/baseline.yaml --scene-dir <capture/basic>
```

使用 YAML mapping 需安裝根目錄 requirements.txt。未指定 --config 時，各 CLI 使用原有預設值。
每次結果保存實際參數快照；相同 experiment ID 下的不同場景需要使用相同共用設定。
基於 Windows／Linux 都能讀取的 JSON 形式寫入 .yaml 快照，為合法 YAML 1.2。
