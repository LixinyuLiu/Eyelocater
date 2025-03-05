import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import sys

class StereoAnnotationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Stereo Annotation Tool")
        self.root.geometry("500x400")
        self.root.resizable(False, False)

        # Set a modern font
        self.custom_font = ("Segoe UI", 10)  # Change to "Roboto" if you have it installed

        # Configure style with the custom font
        self.style = ttk.Style()
        self.style.configure("TLabel", font=self.custom_font)
        self.style.configure("TButton", font=self.custom_font)
        self.style.configure("TEntry", font=self.custom_font)
        self.style.configure("TRadiobutton", font=self.custom_font)

        # Reference file
        self.ref_label = ttk.Label(root, text="Reference h5ad File:")
        self.ref_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.ref_entry = ttk.Entry(root, width=40)
        self.ref_entry.grid(row=0, column=1, padx=10, pady=10)
        self.ref_button = ttk.Button(root, text="Browse", command=self.browse_ref)
        self.ref_button.grid(row=0, column=2, padx=10, pady=10)

        # Reference column
        self.ref_col_label = ttk.Label(root, text="Reference Column:")
        self.ref_col_label.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.ref_col_entry = ttk.Entry(root, width=40)
        self.ref_col_entry.grid(row=1, column=1, padx=10, pady=10)

        # Anatomical region
        self.region_label = ttk.Label(root, text="Anatomical Region:")
        self.region_label.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.region_var = tk.StringVar(value="eye")
        self.region_eye = ttk.Radiobutton(root, text="Eye", variable=self.region_var, value="eye")
        self.region_eye.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        self.region_retina = ttk.Radiobutton(root, text="Retina", variable=self.region_var, value="retina")
        self.region_retina.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        self.region_cornea = ttk.Radiobutton(root, text="Cornea", variable=self.region_var, value="cornea")
        self.region_cornea.grid(row=4, column=1, padx=10, pady=5, sticky="w")

        # Run button
        self.run_button = ttk.Button(root, text="Run Annotation", command=self.run_annotation)
        self.run_button.grid(row=5, column=1, padx=10, pady=20)

        # Output log
        self.log_label = ttk.Label(root, text="Output Log:")
        self.log_label.grid(row=6, column=0, padx=10, pady=10, sticky="w")
        self.log_text = tk.Text(root, height=10, width=50, state="disabled", font=self.custom_font)
        self.log_text.grid(row=6, column=1, columnspan=2, padx=10, pady=10)

    def browse_ref(self):
        file_path = filedialog.askopenfilename(filetypes=[("h5ad files", "*.h5ad")])
        if file_path:
            self.ref_entry.delete(0, tk.END)
            self.ref_entry.insert(0, file_path)

    def run_annotation(self):
        ref_path = self.ref_entry.get()
        ref_col = self.ref_col_entry.get()
        region = self.region_var.get()

        if not ref_path or not ref_col:
            messagebox.showerror("Error", "Please provide all required inputs.")
            return

        # Construct the command
        command = [
            sys.executable,  # Use the same Python interpreter
            "singleR_annotation.py",  # Replace with the actual script name
            "-ref", ref_path,
            "-ref_used_col", ref_col,
            "-data", region
        ]

        # Run the command
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, "Running annotation...\n")
        self.log_text.config(state="disabled")
        self.root.update()

        try:
            result = subprocess.run(command, capture_output=True, text=True)
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, result.stdout)
            self.log_text.insert(tk.END, result.stderr)
            self.log_text.config(state="disabled")
            if result.returncode == 0:
                messagebox.showinfo("Success", "Annotation completed successfully!")
            else:
                messagebox.showerror("Error", "Annotation failed. Check the log for details.")
        except Exception as e:
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, f"Error: {str(e)}\n")
            self.log_text.config(state="disabled")
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = StereoAnnotationApp(root)
    root.mainloop()