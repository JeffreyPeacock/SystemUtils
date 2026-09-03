import tkinter as tk

def test_tkinter():
    root = tk.Tk()
    root.title("Test Window")
    root.geometry("200x100")
    label = tk.Label(root, text="Hello, Tkinter!")
    label.pack(pady=20)
    root.mainloop()

test_tkinter()