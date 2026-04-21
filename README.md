# 肩關節雷射投影量測系統

## 專案簡介

這個專案是用來做肩關節活動範圍量測與練習的半自動化系統。

系統會用相機偵測紅色雷射點，並把對應位置投影到螢幕上；完成校正後，可以進行起點、終點、距離與路徑的量測，並把量測後的路徑拿來做練習引導。

## 主要功能

- 紅色雷射點偵測
- `ArUco`（校正用標記）校正
- `Measurement`（量測模式）：記錄 `START` 到 `END` 的路徑
- `Practice`（練習模式）：顯示最新一次量測完成的路徑
- `Split`（分段數）：設定整條路徑切成幾段
- `Range`（區段範圍）：設定練習時要顯示第幾段到第幾段
- `CSV`（逗號分隔檔）量測摘要輸出
- `JSON`（結構化資料檔）路徑資料輸出

## 畫面說明

### `Control Panel`（控制面板）

主要給操作者使用，顯示：
- 相機畫面
- 工具列按鈕
- 狀態訊息
- 相機設定面板
- 分段數與練習區段

### `Projector Screen`（投影畫面）

主要給受試者使用，顯示：
- 比例尺
- 十字準星
- `START` / `END`
- 量測路徑
- 分段百分比
- `MAX ROM`
- 練習模式高亮路徑

## SOP

### 量測前

1. 開啟相機與投影機。
2. 確認投影幕有進入相機畫面。
3. 確認紅色雷射點能穩定顯示。
4. 必要時用 `Settings`（設定）調整相機參數。

### 校正

1. 按下 `Calibrate`。
2. 確認相機看得到 4 個 `ArUco`。
3. 校正完成後再開始量測。

### 量測

1. 按下 `Split` 設定分段數，預設為 `3`。
2. 按下 `Measure` 進入量測模式。
3. 按一次 `Space` 標記 `START`。
4. 系統開始記錄紅點路徑。
5. 再按一次 `Space` 標記 `END`。
6. 系統自動整理路徑。
7. 需要保存結果時按 `Save CSV`。

### 練習

1. 完成一次量測後，按下 `Practice`。
2. 投影畫面會顯示整理過的路徑。
3. 如只要練部分路徑，按下 `Range`。
4. 輸入起始段與結束段，例如 `2` 到 `3`。

### 重設

1. 按下 `Reset`。
2. 清除本次量測與暫存路徑資料。

## 工具列按鈕

- `Measure`：進入量測模式
- `Practice`：顯示最新練習路徑
- `Range`：設定要顯示第幾段到第幾段
- `Calibrate`：校正
- `Reset`：重設
- `Save CSV`：輸出量測摘要
- `Scale`：設定比例尺實際長度
- `Split`：設定總分段數
- `Full`：切換全螢幕
- `Border`：切換無邊框
- `Settings`：開啟相機設定面板

## 快捷鍵

- `Space`：標記 `START` / `END`
- `C`：校正
- `R`：重設
- `Q`：離開程式

## 輸出資料

### `CSV`

儲存量測摘要，例如：
- 日期時間
- 起點與終點座標
- 總距離
- 分段距離
- 比例尺資訊

### `JSON`

儲存路徑資料，例如：
- 原始路徑點
- 處理後路徑點
- 分段數
- 比例尺資訊

預設存放位置：
- [data/paths](C:\Position\data\paths)

## 主要檔案功能

- [Demo.py](C:\Position\Demo.py)
  - 啟動入口

- [shoulder_rom/app.py](C:\Position\shoulder_rom\app.py)
  - 主流程控制
  - 模式切換
  - 按鈕與快捷鍵行為

- [shoulder_rom/vision.py](C:\Position\shoulder_rom\vision.py)
  - 雷射點偵測
  - 校正運算

- [shoulder_rom/renderer.py](C:\Position\shoulder_rom\renderer.py)
  - `Control Panel` 與 `Projector Screen` 畫面繪製

- [shoulder_rom/path_tools.py](C:\Position\shoulder_rom\path_tools.py)
  - 路徑清理
  - 平滑化
  - 百分比分段切割

- [shoulder_rom/storage.py](C:\Position\shoulder_rom\storage.py)
  - `CSV`、`JSON`、校正檔與設定檔讀寫

- [shoulder_rom/ui_dialogs.py](C:\Position\shoulder_rom\ui_dialogs.py)
  - 輸入視窗與存檔視窗

- [shoulder_rom/config.py](C:\Position\shoulder_rom\config.py)
  - 系統預設參數與路徑設定

- [shoulder_rom/models.py](C:\Position\shoulder_rom\models.py)
  - 狀態資料模型

## 安裝與執行

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

### 校正失敗

- 確認 4 個 `ArUco` 都在畫面內
- 重新按一次 `Calibrate`

### 練習模式沒有路徑

- 先完成一次 `Measure`
- 確認有成功標記 `START` 與 `END`

### 路徑太抖

- 先改善紅點偵測穩定度
- 再重新量測一次
