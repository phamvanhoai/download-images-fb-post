import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from fb_post_image_downloader import download_post_images


DEFAULT_CDP_URL = "http://127.0.0.1:9222"


class DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Facebook Post Image Downloader")
        self.root.geometry("760x520")
        self.root.minsize(720, 500)

        self.output_var = tk.StringVar(value=str((Path.cwd() / "downloads").resolve()))
        self.url_var = tk.StringVar()
        self.cdp_url_var = tk.StringVar(value=DEFAULT_CDP_URL)
        self.status_var = tk.StringVar(value="San sang.")
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self.root.after(150, self._drain_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        container = ttk.Frame(self.root, padding=18)
        container.grid(sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)

        title = ttk.Label(
            container,
            text="Tai anh tu bai viet Facebook",
            font=("Segoe UI", 16, "bold"),
        )
        title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        note = ttk.Label(
            container,
            text=(
                "Dung voi Coc Coc dang mo bang remote debugging. "
                "Khong can chon trinh duyet, profile, hay user data."
            ),
            wraplength=700,
        )
        note.grid(row=1, column=0, sticky="w", pady=(0, 14))

        form = ttk.Frame(container)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        ttk.Label(form, text="Link bai post Facebook").grid(row=0, column=0, sticky="w")
        self.url_entry = ttk.Entry(form, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(form, text="Thu muc luu anh").grid(row=2, column=0, sticky="w")
        folder_row = ttk.Frame(form)
        folder_row.grid(row=3, column=0, sticky="ew", pady=(4, 12))
        folder_row.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(folder_row, textvariable=self.output_var, font=("Segoe UI", 10))
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(folder_row, text="Chon thu muc", command=self._browse_output).grid(row=0, column=1)

        ttk.Label(form, text="CDP URL").grid(row=4, column=0, sticky="w")
        self.cdp_entry = ttk.Entry(form, textvariable=self.cdp_url_var, font=("Segoe UI", 10))
        self.cdp_entry.grid(row=5, column=0, sticky="ew", pady=(4, 12))

        help_box = ttk.LabelFrame(container, text="Cach mo Coc Coc dung")
        help_box.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        help_box.columnconfigure(0, weight=1)

        help_text = tk.Text(
            help_box,
            height=4,
            wrap="word",
            font=("Consolas", 10),
        )
        help_text.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        help_text.insert(
            "1.0",
            '& "C:\\Program Files\\CocCoc\\Browser\\Application\\browser.exe" --remote-debugging-port=9222',
        )
        help_text.configure(state="disabled")

        actions = ttk.Frame(container)
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Button(actions, text="Tai anh", command=self._start_download).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Mo thu muc luu", command=self._open_output_folder).grid(row=0, column=1)

        status = ttk.Label(container, textvariable=self.status_var)
        status.grid(row=5, column=0, sticky="w", pady=(0, 8))

        self.log_text = tk.Text(
            container,
            height=14,
            wrap="word",
            font=("Consolas", 10),
            state="disabled",
        )
        self.log_text.grid(row=6, column=0, sticky="nsew")

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.grid(row=7, column=0, sticky="ew", pady=(12, 0))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if selected:
            self.output_var.set(selected)

    def _open_output_folder(self) -> None:
        path = Path(self.output_var.get()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path.resolve())

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.url_entry.configure(state=state)
        self.output_entry.configure(state=state)
        self.cdp_entry.configure(state=state)
        if running:
            self.progress.start(10)
        else:
            self.progress.stop()

    def _start_download(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Dang chay", "Tool dang tai anh, vui long doi xong.")
            return

        post_url = self.url_var.get().strip()
        output_dir = self.output_var.get().strip()
        cdp_url = self.cdp_url_var.get().strip()

        if not post_url:
            messagebox.showwarning("Thieu link", "Ban hay nhap link bai post Facebook.")
            return
        if not output_dir:
            messagebox.showwarning("Thieu thu muc", "Ban hay chon thu muc luu anh.")
            return
        if not cdp_url:
            messagebox.showwarning("Thieu CDP URL", "Ban hay nhap CDP URL, thuong la http://127.0.0.1:9222")
            return

        self._append_log("-" * 60)
        self._append_log(f"Bat dau tai anh tu: {post_url}")
        self.status_var.set("Dang tai anh...")
        self._set_running(True)

        self.worker = threading.Thread(
            target=self._run_download,
            args=(post_url, output_dir, cdp_url),
            daemon=True,
        )
        self.worker.start()

    def _run_download(self, post_url: str, output_dir: str, cdp_url: str) -> None:
        def logger(message: str) -> None:
            self.log_queue.put(("log", message))

        try:
            saved_files = download_post_images(
                post_url=post_url,
                output_dir=output_dir,
                cdp_url=cdp_url,
                log_callback=logger,
            )
            self.log_queue.put(("success", f"Da tai {len(saved_files)} anh vao {Path(output_dir).resolve()}"))
        except Exception as exc:
            self.log_queue.put(("error", str(exc)))

    def _drain_queue(self) -> None:
        while not self.log_queue.empty():
            kind, payload = self.log_queue.get()
            if kind == "log":
                self._append_log(payload)
            elif kind == "success":
                self._append_log(payload)
                self.status_var.set("Tai anh thanh cong.")
                self._set_running(False)
                messagebox.showinfo("Hoan tat", payload)
            elif kind == "error":
                self._append_log(f"Loi: {payload}")
                self.status_var.set("Tai anh that bai.")
                self._set_running(False)
                messagebox.showerror("Loi", payload)

        self.root.after(150, self._drain_queue)


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = DownloaderApp(root)
    app.url_entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
