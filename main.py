from __future__ import annotations

import tkinter as tk

try:
    from .ui import App
except ImportError:
    from ui import App


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
