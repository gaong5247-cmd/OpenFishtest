"""One-window Windows/Tk local Contributor GUI: Start -> PGN+EPD -> GitHub.

Requires explicitly user-selected executable files; never downloads or runs
untrusted public arena uploads. CPU contribution can be stopped at any time.
"""
from __future__ import annotations

import os
import queue
import shutil
import webbrowser
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from contributor_local import (
    MatchCancelled, play_and_submit, recommended_concurrency
)


class ContributorWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("OpenFishtest · Contributor")
        self.root.geometry("760x690")
        self.root.minsize(620, 600)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.paths = {}
        self.games = tk.StringVar(value="100")
        self.tc = tk.StringVar(value="10+0.1")
        self.concurrency = tk.IntVar(value=recommended_concurrency())
        self.publish = tk.BooleanVar(value=True)
        self.approved = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="준비 완료 · 엔진 EXE 3개와 북 파일을 선택하세요.")

        self._render()
        self.root.after(160, self._poll_messages)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _render(self):
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="♞ OpenFishtest · Contributor",
                  font=("Segoe UI", 19, "bold")).pack(anchor="w")
        ttk.Label(frame,
                  text="로컬 CPU로 대국 → 결과 PGN/EPD만 GitHub 자동 제출 (관리자 토큰 불필요)",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))

        file_frame = ttk.LabelFrame(frame, text="로컬에서 실행할 파일 선택", padding=10)
        file_frame.pack(fill="x")
        specs = [
            ("fastchess", "Fastchess 프로그램", "Fastchess", "*.exe *.bin *"),
            ("stockless", "Stockless 기준 엔진", "UCI Engine", "*.exe *.bin *"),
            ("challenger", "도전 엔진", "UCI Engine", "*.exe *.bin *"),
            ("book", "오프닝북 (.epd / .pgn)", "Opening Book", "*.epd *.pgn"),
        ]
        for key, label, file_type, pattern in specs:
            row = ttk.Frame(file_frame)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=label, width=23).pack(side="left")
            variable = tk.StringVar()
            self.paths[key] = variable
            entry = ttk.Entry(row, textvariable=variable, state="readonly")
            entry.pack(side="left", fill="x", expand=True, padx=(5, 8))
            ttk.Button(row, text="파일 선택", command=lambda k=key,p=pattern,t=file_type:
                       self._browse(k,p,t)).pack(side="right")

        settings = ttk.LabelFrame(frame, text="대국 및 CPU 설정", padding=10)
        settings.pack(fill="x", pady=12)
        line = ttk.Frame(settings)
        line.pack(fill="x", pady=4)
        ttk.Label(line, text="동시 대국", width=12).pack(side="left")
        slider_max = max(1, min(12, (os.cpu_count() or 2) // 1))
        ttk.Scale(
            line, from_=1, to=slider_max, variable=self.concurrency
        ).pack(side="left", fill="x", expand=True, padx=10)
        self.cpu_label = ttk.Label(line, text="")
        self.cpu_label.pack(side="right")
        self.concurrency.trace_add("write", self._set_cpu_label)
        self._set_cpu_label()

        line2 = ttk.Frame(settings)
        line2.pack(fill="x", pady=(9, 2))
        ttk.Label(line2, text="대국 수", width=12).pack(side="left")
        ttk.Combobox(line2, textvariable=self.games, width=9,
                     values=["20", "100", "200"], state="readonly").pack(side="left")
        ttk.Label(line2, text="시간제어", padding=(25, 0, 8, 0)).pack(side="left")
        ttk.Combobox(line2, textvariable=self.tc, width=12,
                     values=["10+0.1", "60+0.6", "100+1", "1+0.01"],
                     state="readonly").pack(side="left")

        ttk.Checkbutton(
            settings, text="대국 종료 시 자동 공개 (저장소 소유자는 PR 없이 직접 업로드)",
            variable=self.publish
        ).pack(anchor="w", pady=3)
        ttk.Checkbutton(
            settings,
            text="선택한 로컬 엔진 EXE가 신뢰 가능한 파일임을 확인했고, CPU 사용에 동의합니다.",
            variable=self.approved
        ).pack(anchor="w", pady=3)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=6)
        self.start = ttk.Button(
            actions, text="▶ CPU 기여 시작 · 자동 대국",
            command=self._start
        )
        self.start.pack(side="left", fill="x", expand=True)
        self.stop = ttk.Button(
            actions, text="■ 대국 중단",
            command=self._stop, state="disabled"
        )
        self.stop.pack(side="left", padx=(10, 0))
        quick_actions = ttk.Frame(frame)
        quick_actions.pack(fill="x", pady=(3, 7))
        ttk.Button(
            quick_actions, text="↑ 기존 PGN·EPD 게시 사이트",
            command=self._open_upload_page
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            quick_actions, text="📂 로컬 대국 결과 폴더",
            command=self._open_results_folder
        ).pack(side="left", fill="x", expand=True, padx=(9, 0))
        ttk.Label(frame, textvariable=self.status,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=4)

        log_box = ttk.LabelFrame(frame, text="자동 대국 · 제출 로그", padding=7)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=9, state="disabled", wrap="word",
                           bg="#0e182a", fg="#d9f3e5", font=("Consolas", 10))
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        self._message(
            "GitHub 인증은 Contributor 본인의 계정으로 최초 1회 "
            "'gh auth login'을 실행해야 합니다. GitHub Pages는 "
            "결과 화면만 제공하며, PC에서 UCI 대국을 수행합니다."
        )

    def _open_upload_page(self):
        # Website only stages data via the owner's explicit GitHub token.
        # This does not silently upload files or access local disk.
        webbrowser.open(
            "https://gaong5247-cmd.github.io/OpenFishtest/upload.html",
            new=2
        )

    def _open_results_folder(self):
        folder = Path.home() / "OpenFishtest-Results"
        folder.mkdir(exist_ok=True)
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            webbrowser.open(folder.resolve().as_uri())

    def _browse(self, key, pattern, label):
        selected = filedialog.askopenfilename(
            title=label,
            filetypes=[(label, pattern), ("All files", "*")]
        )
        if selected:
            self.paths[key].set(selected)

    def _set_cpu_label(self, *_args):
        value = max(1, round(self.concurrency.get()))
        self.cpu_label.configure(text=f"{value}판 · 약 {2 * value}개 엔진 스레드")

    def _message(self, value):
        self.log.configure(state="normal")
        self.log.insert("end", str(value) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        if self.busy:
            return
        if not self.approved.get():
            messagebox.showwarning(
                "실행 동의 필요",
                "본인이 신뢰하는 엔진 EXE와 CPU 기여에 동의해야 실행됩니다."
            )
            return
        try:
            paths = {
                key: Path(value.get()).expanduser().resolve(strict=True)
                for key,value in self.paths.items()
            }
            if not all(path.is_file() for path in paths.values()):
                raise ValueError("파일 네 개를 모두 선택해 주세요.")
            games = int(self.games.get())
            threads = int(round(self.concurrency.get()))
            auto = self.publish.get()
            tc = self.tc.get()
            if auto and (not shutil.which("gh") or not shutil.which("git")):
                raise ValueError(
                    "자동 제출에는 GitHub CLI와 Git이 필요합니다. "
                    "'gh auth login'으로 한 번만 인증하세요."
                )
        except (ValueError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("설정 오류", str(exc))
            return

        self.busy = True
        self.stop_event.clear()
        self.start.configure(state="disabled")
        self.stop.configure(state="normal")
        self.status.set("Fastchess 대국 실행 중…")
        self._message("▶ 대국 시작: 실제 UCI 수순만 제출됩니다.")

        def execute():
            try:
                outcome = play_and_submit(
                    paths["fastchess"], paths["stockless"],
                    paths["challenger"], paths["book"],
                    concurrency=threads, games=games,
                    tc=tc, stop_event=self.stop_event,
                    progress=lambda line: self.events.put(("log", line)),
                    submit=auto
                )
                self.events.put(("success", outcome))
            except (Exception,) as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("finished", None))

        threading.Thread(target=execute, daemon=True).start()

    def _stop(self):
        self.stop_event.set()
        self.status.set("대국 중단 요청 · 실행 중 프로세스 종료 중…")
        self._message("■ 사용자가 CPU 기여를 중단했습니다.")

    def _poll_messages(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._message(value)
                elif kind == "error":
                    self._message("오류: " + value)
                    self.status.set("실패 · 로그를 확인하세요")
                elif kind == "success":
                    self._message(
                        "완료! " + (
                            value.get("pull_request", "로컬 PGN/EPD 생성")
                        )
                    )
                    self.status.set(
                        "GitHub 자동 검증 대기" if value["submitted"]
                        else "로컬 대국 종료"
                    )
                elif kind == "finished":
                    self.busy = False
                    self.start.configure(state="normal")
                    self.stop.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(160, self._poll_messages)

    def _close(self):
        if self.busy:
            if not messagebox.askyesno(
                "대국 중단",
                "대국이 진행 중입니다. CPU 기여를 중단하고 종료할까요?"
            ):
                return
            self.stop_event.set()
            messagebox.showinfo(
                "중단 요청",
                "Fastchess 프로세스를 종료하고 프로그램을 다시 닫으세요."
            )
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    ContributorWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
