import tkinter as tk
from tkinter import ttk
import threading

def setup_root_window():
    root = tk.Tk()
    root.title("Duplicate Files")
    root.geometry("800x600")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=1)
    return root

def setup_frame(parent, row, column):
    frame = ttk.Frame(parent, padding="10")
    frame.grid(row=row, column=column, sticky="nsew")
    return frame

def setup_canvas(frame):
    canvas = tk.Canvas(frame)
    scrollbar_y = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    scrollbar_x = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
    scrollable_frame = ttk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        )
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar_y.pack(side="right", fill="y")
    scrollbar_x.pack(side="bottom", fill="x")

    return canvas, scrollable_frame

def create_checkboxes(scrollable_frame, duplicates, start_index, end_index):
    checkboxes = []
    for md5sum, paths in list(duplicates.items())[start_index:end_index]:
        if len(paths) > 1:
            left_var = tk.BooleanVar()
            right_var = tk.BooleanVar()
            checkboxes.append((left_var, right_var))
            ttk.Checkbutton(scrollable_frame, text=paths[0], variable=left_var).pack(anchor="w")
            ttk.Checkbutton(scrollable_frame, text=paths[1], variable=right_var).pack(anchor="w")
    return checkboxes

def load_page(scrollable_frame, duplicates, page, items_per_page):
    for widget in scrollable_frame.winfo_children():
        widget.destroy()
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    return create_checkboxes(scrollable_frame, duplicates, start_index, end_index)

def show_duplicates_gui(duplicates):
    root = setup_root_window()

    left_frame = setup_frame(root, 0, 0)
    right_frame = setup_frame(root, 0, 1)

    left_canvas, left_scrollable_frame = setup_canvas(left_frame)
    right_canvas, right_scrollable_frame = setup_canvas(right_frame)

    items_per_page = 50
    current_page = 0
    total_pages = (len(duplicates) + items_per_page - 1) // items_per_page

    left_checkboxes = []
    right_checkboxes = []

    def load_page_async(page):
        nonlocal left_checkboxes, right_checkboxes
        left_checkboxes = load_page(left_scrollable_frame, duplicates, page, items_per_page)
        right_checkboxes = load_page(right_scrollable_frame, duplicates, page, items_per_page)

    def next_page():
        nonlocal current_page
        if current_page < total_pages - 1:
            current_page += 1
            load_page_async(current_page)

    def previous_page():
        nonlocal current_page
        if current_page > 0:
            current_page -= 1
            load_page_async(current_page)

    load_page_async(0)

    def write_rm_commands():
        with open("rm_commands.txt", "w") as f:
            for left_var, right_var in left_checkboxes:
                if left_var.get():
                    f.write(f"rm {left_var}\n")
                if right_var.get():
                    f.write(f"rm {right_var}\n")

    nav_frame = ttk.Frame(root)
    nav_frame.grid(row=1, column=0, columnspan=2, pady=10)
    prev_button = ttk.Button(nav_frame, text="Previous", command=previous_page)
    prev_button.pack(side="left", padx=5)
    next_button = ttk.Button(nav_frame, text="Next", command=next_page)
    next_button.pack(side="left", padx=5)

    delete_button = ttk.Button(root, text="Write rm Commands", command=write_rm_commands)
    delete_button.grid(row=2, column=0, columnspan=2, pady=10)

    root.mainloop()