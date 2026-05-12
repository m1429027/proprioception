# 肩關節雷射投影量測系統

## 專案簡介

這個專案是用來做肩關節活動範圍量測、練習與考試的半自動化系統。

系統會用相機偵測紅色雷射點，並把對應位置投影到螢幕上。完成 `ArUco`（校正用標記）校正後，可以量測 `START` 到 `END` 的移動路徑，將路徑分段做練習，並在考試模式中記錄多個 `trial`（回合）後輸出成 `Excel`（試算表）檔。

## 目前主要功能

- 紅色雷射點偵測
- `ArUco` 校正
- 四模式操作介面：
  - `Initial`
  - `Measure`
  - `Practice`
  - `Exam`
- `Measure`：記錄 `START` 到 `END` 的紅點路徑
- `Practice`：依照儲存後的路徑做分段顯示與練習
- `Exam`：設定多個 `trial`，逐回合記錄 `x / y / time`
- `Exam`：支援多個 `segment`，每個 `segment` 以相同 `trial` 數進行考試
- `Split`（分段數）：設定整條路徑切成幾段
- `Range`（區段範圍）：設定從 `START` 顯示到第幾個分點
- `Path JSON`（路徑資料檔）輸出
- `Exam Excel`（考試試算表）輸出

## 畫面分工

### `Control Panel`（控制面板）

主要給操作者使用，顯示：

- 相機畫面
- 四模式分頁
- 當前模式按鈕
- 狀態訊息
- 相機設定面板
- 受試者資料夾狀態
- 最新一筆 `Exam` 誤差資訊

### `Projector Screen`（投影畫面）

主要給受試者使用，顯示：

- 比例尺
- 十字準星
- `START` / `END`
- 量測路徑
- 分段百分比
- `MAX ROM`
- `Practice` 或 `Exam` 的參考路徑高亮區段

## 四模式說明

### `Initial`

用來做量測前準備：

- `Calibrate`
- `Settings`
- `Scale`
- `Full`
- `Border`
- `Subject`

這個模式要先完成受試者資料夾設定，後面才能進 `Measure`、`Practice`、`Exam`。

### `Measure`

用來建立正式路徑：

- `Reset Path`
- `Split`
- `Save Path`

操作方式：

1. 按 `Space` 標記 `START`
2. 紅點移動過程會持續記錄路徑
3. 再按一次 `Space` 標記 `END`
4. 系統會整理路徑
5. 按 `Save Path` 後，才能進 `Practice` 或 `Exam`

### `Practice`

用來依照剛儲存的路徑做練習：

- `Range`

操作方式：

1. 先完成 `Measure`
2. 先 `Save Path`
3. 進入 `Practice`
4. 如只要顯示部分路徑，按 `Range`
5. 輸入要顯示到第幾個分點

### `Exam`

用來做考試回合記錄：

- `Range`
- `Reset Trial`
- `Save Exam`

操作方式：

1. 先完成 `Measure`
2. 先 `Save Path`
3. 進入 `Exam`
4. 設定要做幾個 `trial`
5. 先按 `Range` 選擇這次考到第幾個分點
6. 每個 `trial` 依序按三次 `Space`
   - 第一次：標記 `start`
   - 第二次：標記 `target`
   - 第三次：標記 `end`
7. 做完一個 `segment` 的全部 `trial` 後，可再選下一個 `Range`
8. 全部 `segment` 完成後，按 `Save Exam` 一次輸出 `Excel`

## SOP

### 量測前

1. 開啟相機與投影機。
2. 確認投影畫面有進入相機視野。
3. 確認紅色雷射點可穩定顯示。
4. 進入 `Initial` 模式。
5. 設定 `Subject`（受試者資料夾）。
6. 必要時開啟 `Settings` 調整相機參數。
7. 若紅點框有小幅飄動，可在 `Settings` 中調整 `Stability`（穩定度）。

### 校正

1. 在 `Initial` 模式按下 `Calibrate`。
2. 確認相機看得到 4 個 `ArUco`。
3. 校正完成後再進行量測。

### 量測

1. 進入 `Measure`。
2. 按 `Split` 設定分段數。
3. 按一次 `Space` 標記 `START`。
4. 移動紅點到終點。
5. 再按一次 `Space` 標記 `END`。
6. 系統整理路徑。
7. 按 `Save Path` 儲存路徑。

### 練習

1. 進入 `Practice`。
2. 投影畫面會顯示參考路徑。
3. 如只要顯示部分路徑，按 `Range`。
4. 輸入從 `START` 到第幾個分點。

### 考試

1. 進入 `Exam`。
2. 設定 `trial` 數量。
3. 按 `Range` 選擇這次要考到第幾個分點。
4. 每回合按三次 `Space`：
   - 第一次標記 `start`
   - 第二次標記 `target`
   - 第三次標記 `end`
5. 每個 `trial` 完成後，`Control Panel` 會顯示該回合的 `start error / target error / end error`。
6. 若上一個回合做不好，可按 `Reset Trial` 重做上一個已完成回合。
7. 做完一個 `segment` 後，可選下一個 `Range` 繼續記錄。
8. 全部完成後按 `Save Exam`。

## 操作限制

- 未先設定 `Subject Folder`，不能進入 `Measure`、`Practice`、`Exam`
- 未先 `Save Path`，不能進入 `Practice`、`Exam`
- 若量測完成後又修改 `Split` 或 `Scale`，需要重新 `Save Path`
- `Exam` 不會在最後一個 `trial` 自動存檔，必須手動按 `Save Exam`
- `Exam` 必須先設定 `Range` 才能開始當前 `segment`

## 快捷鍵

- `Space`
  - `Measure`：標記 `START / END`
  - `Exam`：依序標記 `start / target / end`
- `C`：校正
- `Q`：離開程式

## 路徑邏輯

目前量測路徑的處理方式是：

1. 在 `START` 到 `END` 之間持續記錄紅點座標
2. 去除連續重複點
3. 排除極端跳點
4. 對中間路徑做較保守的平滑
5. 保留原始 `START` 與 `END`

目標是讓路徑盡量貼近受試者實際移動軌跡，而不是用捷徑簡化成一條過度平順的線。

## 輸出資料

所有正式輸出都存到同一位受試者資料夾中。

### `Path JSON`

檔名格式：

- `YYYYMMDD_HHMMSS_path.json`

內容包含：

- 原始路徑點
- 處理後路徑點
- 分段數
- 比例尺資訊

### `Exam Excel`

檔名格式：

- `YYYYMMDD_HHMMSS_data.xlsx`

內容包含：

- 每個 `segment` 一個獨立 `sheet`
- 每個 `trial` 的 `x / y / time / event`
- 每個 `trial` 的 `start point / target point / end point`
- 每個 `trial` 的 `start error / target error / end error`（`cm`）
- 每個 `trial` 的 `total time`
- 最後一個 `Path` `sheet`，列出本次量測的參考路徑 `x / y`

## 主要檔案功能

- [Demo.py](C:\Position\Demo.py)
  - 啟動入口

- [shoulder_rom/app.py](C:\Position\shoulder_rom\app.py)
  - 主流程控制
  - 模式切換
  - 路徑與考試流程

- [shoulder_rom/vision.py](C:\Position\shoulder_rom\vision.py)
  - 雷射點偵測
  - 校正運算

- [shoulder_rom/renderer.py](C:\Position\shoulder_rom\renderer.py)
  - `Control Panel` 與 `Projector Screen` 畫面繪製

- [shoulder_rom/path_tools.py](C:\Position\shoulder_rom\path_tools.py)
  - 路徑去重
  - 跳點過濾
  - 平滑化
  - 百分比分段切割

- [shoulder_rom/storage.py](C:\Position\shoulder_rom\storage.py)
  - `Path JSON`、`Exam Excel`、校正檔與設定檔讀寫

- [shoulder_rom/ui_dialogs.py](C:\Position\shoulder_rom\ui_dialogs.py)
  - 輸入視窗
  - 受試者資料夾選取 / 建立

- [shoulder_rom/config.py](C:\Position\shoulder_rom\config.py)
  - 系統預設參數與路徑設定

- [shoulder_rom/models.py](C:\Position\shoulder_rom\models.py)
  - 狀態資料模型

## 安裝與執行

### 建議交接方式

目前最建議在新的 Windows 電腦上使用：

- `Conda`（Python 環境管理工具）建立獨立環境
- 再用 `pip install -r requirements.txt`

本專案目前實際驗證的 Python 版本為：

- `Python 3.8`

### 使用 `conda`（建議）

```powershell
conda create -n position python=3.8 -y
conda activate position
pip install -r requirements.txt
python Demo.py
```

### 使用 `uv`（Python 環境工具）

```powershell
uv sync
uv run python Demo.py
```

### 使用 `pip`

```powershell
pip install -r requirements.txt
python Demo.py
```

## 常見問題

### 偵測不到紅點

- 調整 `Exposure`
- 調整 `Focus`
- 調整 `Min Bright`
- 調整 `Min Area`
- 調整 `Ignore Bot`
- 若紅點沒動但偵測框仍浮動，可調整 `Stability`

### Stability 說明

`Settings` 內的 `Stability` 用來控制紅點框的穩定度，範圍為 `1 ~ 5`。

- `1`：較靈敏，框比較跟手，但也比較容易抖
- `3`：平衡，適合一般使用
- `5`：較穩定，框比較不會飄，但移動時會稍微比較黏

若遇到：

- 雷射點固定不動，但框一直小幅浮動：把 `Stability` 調高
- 雷射點移動時，框感覺太慢、太黏：把 `Stability` 調低

### 校正失敗

- 確認 4 個 `ArUco` 都在畫面內
- 重新按一次 `Calibrate`

### 不能進 `Practice` 或 `Exam`

- 先確認是否已設定 `Subject Folder`
- 先確認是否已完成量測
- 先確認是否已按 `Save Path`

### 路徑看起來不對

- 先確認紅點偵測是否穩定
- 重新做一次量測
- 若量測後修改過 `Split` 或 `Scale`，要重新 `Save Path`

### `Exam` 無法存檔

- 確認所有 `trial` 都已完成
- 確認目前 `segment` 已完成，沒有停在中途
- 確認最後有按 `Save Exam`
