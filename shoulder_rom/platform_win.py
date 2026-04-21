import ctypes
import sys


def toggle_borderless(window_name: str, is_borderless: bool) -> bool:
    if sys.platform != "win32":
        return is_borderless

    hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
    if not hwnd:
        return is_borderless

    new_state = not is_borderless
    style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
    caption = 0x00C00000
    thickframe = 0x00040000

    if new_state:
        style = style & ~caption
        style = style & ~thickframe
    else:
        style = style | caption
        style = style | thickframe

    ctypes.windll.user32.SetWindowLongW(hwnd, -16, style)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)
    return new_state
