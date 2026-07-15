"""Capture only an X11 client window, excluding compositor/desktop contents."""

import ctypes
import ctypes.util

from PIL import Image


class XImage(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int),
        ("bitmap_bit_order", ctypes.c_int),
        ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("bytes_per_line", ctypes.c_int),
        ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
    ]


def capture(root, path):
    root.update()
    xlib = ctypes.CDLL(ctypes.util.find_library("X11"))
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XGetImage.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_ulong,
        ctypes.c_int,
    ]
    xlib.XGetImage.restype = ctypes.POINTER(XImage)
    xlib.XDestroyImage.argtypes = [ctypes.POINTER(XImage)]
    display = xlib.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Cannot open X11 display for native window capture.")
    image = None
    try:
        image = xlib.XGetImage(
            display,
            root.winfo_id(),
            0,
            0,
            root.winfo_width(),
            root.winfo_height(),
            ctypes.c_ulong(-1).value,
            2,
        )
        if not image:
            raise RuntimeError("XGetImage failed for the application window.")
        v = image.contents
        if (
            v.bits_per_pixel != 32
            or v.byte_order != 0
            or (v.red_mask, v.green_mask, v.blue_mask) != (0xFF0000, 0xFF00, 0xFF)
        ):
            raise RuntimeError("Unsupported pixel format for window capture.")
        raw = ctypes.string_at(v.data, v.bytes_per_line * v.height)
        Image.frombytes(
            "RGB", (v.width, v.height), raw, "raw", "BGRX", v.bytes_per_line
        ).save(path)
    finally:
        if image:
            xlib.XDestroyImage(image)
        xlib.XCloseDisplay(display)
