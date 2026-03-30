import cv2
import numpy as np
import sys
import cv2.aruco as aruco
import json
import math
import tkinter as tk
from tkinter import simpledialog, filedialog, messagebox
from datetime import datetime

# === 設定區 ===
CAMERA_ID = 0 
SCREEN_W = 1920
SCREEN_H = 1080
SCALE_PX = 50  # 比例尺的固定像素長度
# ============

try:
    ARUCO_DICT = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    ARUCO_PARAMS = aruco.DetectorParameters()
except:
    print("錯誤：請安裝 opencv-contrib-python")
    sys.exit(1)

def nothing(x):
    pass

# 初始化 Tkinter (用於彈出輸入框與存檔視窗，隱藏主視窗)
tk_root = tk.Tk()
tk_root.withdraw() 
tk_root.attributes('-topmost', True) # 讓彈出視窗永遠在最上層

# 1. 啟動相機 (DSHOW 模式確保曝光設定生效)
if sys.platform == 'win32':
    cap = cv2.VideoCapture(CAMERA_ID, cv2.CAP_DSHOW)
else:
    cap = cv2.VideoCapture(CAMERA_ID)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_AUTOFOCUS, 0) # 關閉自動對焦以允許手動控制

# 2. 建立視窗與 UI
cv2.namedWindow('Control Panel', cv2.WINDOW_NORMAL)
cv2.resizeWindow('Control Panel', 640, 500) 
cv2.namedWindow('Projector Screen', cv2.WINDOW_NORMAL)
cv2.resizeWindow('Projector Screen', 800, 600)

projector_bg = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8) 

# 控制參數
cv2.createTrackbar('Exposure', 'Control Panel', 6, 13, nothing) 
cv2.createTrackbar('Focus', 'Control Panel', 0, 255, nothing)
cv2.createTrackbar('Min Bright', 'Control Panel', 230, 255, nothing)
cv2.createTrackbar('Min Area', 'Control Panel', 5, 200, nothing)
cv2.createTrackbar('Ignore Bot', 'Control Panel', 100, 300, nothing) 

# 全域變數
homography_matrix = None
calibrating = False
is_fullscreen = False
rom_state = 0 # 0: 待機, 1: 已定起點, 2: 已定終點
p_start = None 
p_end = None   
measured_points = [] 
scale_cm = 50.0 # 預設比例尺真實長度 (公分)

# 載入校正檔
try:
    with open("calibration_data_cv.json", "r") as f:
        homography_matrix = np.array(json.load(f)["homography"])
    print("✅ 已載入校正檔")
except:
    print("⚠️ 無校正檔，請按 'c' 進行校正")

print("=== ROM 評估系統啟動 (含存檔功能版) ===")
print(" [Space] 設定點位 | [r] 重置測量 | [c] 校正")
print(" [v] 輸入比例尺公分數 | [s] 儲存紀錄 | [f] 全螢幕 | [q] 離開")

# === 開始執行主迴圈並加入保險結構 ===
try:
    while True:
        ret, frame = cap.read()
        if not ret: break

        h, w = frame.shape[:2]
        
        # 參數讀取與設定
        exp_val = cv2.getTrackbarPos('Exposure', 'Control Panel')
        focus_val = cv2.getTrackbarPos('Focus', 'Control Panel')
        min_bright = cv2.getTrackbarPos('Min Bright', 'Control Panel')
        min_area = cv2.getTrackbarPos('Min Area', 'Control Panel')
        ignore_bot = cv2.getTrackbarPos('Ignore Bot', 'Control Panel')
        
        # 計算換算比例
        cm_per_px = scale_cm / SCALE_PX # 每 1 pixel 代表的真實公分數

        cap.set(cv2.CAP_PROP_EXPOSURE, -1 * (13 - exp_val))
        cap.set(cv2.CAP_PROP_FOCUS, focus_val)

        # 影像前處理
        proc_frame = frame.copy()
        if ignore_bot > 0:
            cv2.rectangle(proc_frame, (0, h - ignore_bot), (w, h), (0, 0, 0), -1)

        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)
        _, mask_bright = cv2.threshold(gray, min_bright, 255, cv2.THRESH_BINARY)
        hsv = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2HSV)
        lower_red1, upper_red1 = np.array([0, 100, 100]), np.array([10, 255, 255])
        lower_red2, upper_red2 = np.array([160, 100, 100]), np.array([180, 255, 255])
        mask_red = cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)
        mask = cv2.bitwise_or(mask_bright, mask_red)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

        control_view = frame.copy() 
        cv2.line(control_view, (0, h - ignore_bot), (w, h - ignore_bot), (0, 0, 255), 2)
        
        projector_view = np.zeros_like(projector_bg) 
        current_laser_pos = None 
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > min_area:
                ((cx, cy), radius) = cv2.minEnclosingCircle(largest)
                
                if homography_matrix is not None:
                    pt_cam = np.array([[[cx, cy]]], dtype=np.float32)
                    pt_screen = cv2.perspectiveTransform(pt_cam, homography_matrix)
                    sx, sy = int(pt_screen[0][0][0]), int(pt_screen[0][0][1])
                    
                    # 座標範圍限縮
                    if 0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H:
                        current_laser_pos = (sx, sy)
                        cv2.circle(control_view, (int(cx), int(cy)), int(radius + 10), (0, 255, 0), 2)
                    else:
                        cv2.circle(control_view, (int(cx), int(cy)), int(radius + 10), (0, 0, 255), 1)
                else:
                    cv2.circle(control_view, (int(cx), int(cy)), int(radius + 10), (0, 255, 0), 2)

        # 繪圖邏輯
        if calibrating:
            ph, pw = projector_view.shape[:2]
            margin, size = 150, 200
            positions = {0:(margin, margin), 1:(pw-margin-size, margin), 2:(pw-margin-size, ph-margin-size), 3:(margin, ph-margin-size)}
            marker_centers = {}
            for m_id, (px, py) in positions.items():
                cv2.rectangle(projector_view, (px-10, py-10), (px+size+10, py+size+10), (255, 255, 255), -1)
                marker_img = aruco.generateImageMarker(ARUCO_DICT, m_id, size)
                projector_view[py:py+size, px:px+size] = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2BGR)
                marker_centers[m_id] = (px + size/2, py + size/2)
            
            cv2.putText(projector_view, "CALIBRATING MODE", (pw//2 - 200, ph//2), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
            
            corners, ids, _ = aruco.detectMarkers(gray, ARUCO_DICT, parameters=ARUCO_PARAMS)
            if ids is not None and len(ids) >= 4:
                src_pts, dst_pts, id_list = [], [], ids.flatten().tolist()
                if all(x in id_list for x in [0, 1, 2, 3]):
                    for i, m_id in enumerate(id_list):
                        if m_id in marker_centers:
                            c = corners[i][0]
                            src_pts.append([np.mean(c[:, 0]), np.mean(c[:, 1])])
                            dst_pts.append(marker_centers[m_id])
                    homography_matrix, _ = cv2.findHomography(np.array(src_pts, dtype=np.float32), np.array(dst_pts, dtype=np.float32), cv2.RANSAC, 5.0)
                    with open("calibration_data_cv.json", "w") as f: json.dump({"homography": homography_matrix.tolist()}, f)
                    print("校正完成")
                    calibrating = False 
        else:
            # === 繪製固定比例尺 ===
            bar_start_x, bar_start_y = 50, SCREEN_H - 50
            bar_end_x = bar_start_x + SCALE_PX
            
            cv2.line(projector_view, (bar_start_x, bar_start_y), (bar_end_x, bar_start_y), (255, 255, 255), 3)
            cv2.line(projector_view, (bar_start_x, bar_start_y - 15), (bar_start_x, bar_start_y + 15), (255, 255, 255), 3)
            cv2.line(projector_view, (bar_end_x, bar_start_y - 15), (bar_end_x, bar_start_y + 15), (255, 255, 255), 3)
            
            # 提示字樣
            cv2.putText(projector_view, f"Scale: {scale_cm} cm (Press 'v' to change)", (bar_start_x, bar_start_y - 25), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)

            # 畫出起點
            if p_start:
                cv2.circle(projector_view, p_start, 5, (255, 255, 0), -1)
                cv2.putText(projector_view, "START", (p_start[0]+20, p_start[1]), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

            # 畫出終點、三分刻度與真實距離
            if rom_state == 2 and p_start and p_end:
                cv2.circle(projector_view, p_end, 5, (0, 255, 0), -1)
                cv2.line(projector_view, p_start, p_end, (0, 255, 255), 2)
                
                dx, dy = p_end[0] - p_start[0], p_end[1] - p_start[1]
                dist_px = math.sqrt(dx*dx + dy*dy)
                
                # 計算真實距離
                real_dist_cm = dist_px * cm_per_px
                info_text = f"MAX: {real_dist_cm:.1f} cm"
                cv2.putText(projector_view, info_text, (p_end[0]+20, p_end[1]+35), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)

                if dist_px > 0:
                    vx, vy = -dy/dist_px, dx/dist_px
                    t_len = 40 
                    for ratio, label in [(0.33, "33%"), (0.66, "66%")]:
                        px = int(p_start[0] + dx * ratio)
                        py = int(p_start[1] + dy * ratio)
                        pt1 = (int(px + vx * t_len), int(py + vy * t_len))
                        pt2 = (int(px - vx * t_len), int(py - vy * t_len))
                        cv2.line(projector_view, pt1, pt2, (255, 255, 255), 3)
                        cv2.putText(projector_view, label, (pt1[0]+10, pt1[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            # 畫即時準心
            if current_laser_pos:
                sx, sy = current_laser_pos
                cv2.line(projector_view, (sx-40, sy), (sx+40, sy), (0, 255, 0), 2)
                cv2.line(projector_view, (sx, sy-40), (sx, sy+40), (0, 255, 0), 2)
                cv2.circle(projector_view, (sx, sy), 20, (0, 255, 0), 2)

        # 視窗顯示
        cv2.imshow('Control Panel', control_view)
        cv2.imshow('Projector Screen', projector_view)

        # 按鍵處理
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): 
            break
        elif key == ord('c'): 
            calibrating = not calibrating
        elif key == ord('f'):
            is_fullscreen = not is_fullscreen
            cv2.setWindowProperty('Projector Screen', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if is_fullscreen else cv2.WINDOW_NORMAL)
        elif key == ord('r'): 
            p_start, p_end, rom_state = None, None, 0
            print("重置測量")
        elif key == ord('v'): 
            new_scale = simpledialog.askfloat("設定比例尺", "請輸入左下角白線的真實長度 (公分):", 
                                              initialvalue=scale_cm, minvalue=0.1, parent=tk_root)
            if new_scale is not None:
                scale_cm = new_scale
                print(f"✅ 比例尺已更新: {SCALE_PX}px = {scale_cm} cm")
                
        # === [新增] 存檔功能 ===
        elif key == ord('s'):
            # 確認已經測量完畢 (有起點與終點)
            if rom_state == 2 and p_start and p_end:
                # 1. 重新計算距離
                dx, dy = p_end[0] - p_start[0], p_end[1] - p_start[1]
                total_cm = math.sqrt(dx*dx + dy*dy) * cm_per_px
                one_third_cm = total_cm / 3.0
                two_third_cm = total_cm * 2.0 / 3.0
                
                # 2. 準備字串格式
                now = datetime.now()
                date_str = now.strftime("%Y/%m/%d")
                time_str = now.strftime("%H:%M")
                record_str = f"日期:{date_str} 時間:{time_str} 總活動距離:{total_cm:.1f}cm 三分之一:{one_third_cm:.1f}cm 三分之二:{two_third_cm:.1f}cm\n"
                
                # 3. 詢問儲存方式 (附加 or 另存)
                choice = messagebox.askyesnocancel("儲存方式", "是否要將紀錄「附加到現有檔案」？\n\n[是] 開啟舊檔並加入新紀錄\n[否] 建立全新的文字檔\n[取消] 不儲存", parent=tk_root)
                
                if choice is True: # 開啟舊檔 (Append)
                    filepath = filedialog.askopenfilename(title="選擇要附加的檔案", filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")], parent=tk_root)
                    if filepath:
                        with open(filepath, 'a', encoding='utf-8') as f:
                            f.write(record_str)
                        print(f"📁 紀錄已成功附加至: {filepath}")
                        
                elif choice is False: # 另存新檔 (Save As)
                    filepath = filedialog.asksaveasfilename(title="另存新檔", defaultextension=".txt", filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")], parent=tk_root)
                    if filepath:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(record_str)
                        print(f"📝 紀錄已另存新檔: {filepath}")
            else:
                messagebox.showwarning("無法儲存", "請先完成起點與終點的測量！", parent=tk_root)

        elif key == ord(' '):
            if current_laser_pos:
                if rom_state == 0:
                    p_start, rom_state = current_laser_pos, 1
                    print(f"起點設定: {p_start}")
                elif rom_state == 1:
                    p_end, rom_state = current_laser_pos, 2
                    print(f"終點設定: {p_end}")

finally:
    cap.release()
    cv2.destroyAllWindows()
    tk_root.destroy() 
    print("系統已安全釋放相機資源並關閉視窗")