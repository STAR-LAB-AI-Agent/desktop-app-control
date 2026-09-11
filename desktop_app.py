"""始终置顶的极简桌面 Agent 任务框。"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox

from desktop_agent import DesktopAgent
from desktop_agent.task import ReviewDecision, TaskResult, TaskStatus
from main import build_agent_config


PLACEHOLDER = "输入桌面任务，按 Enter 执行"


class DesktopAgentWindow:
    def __init__(self) -> None:
        self.config = build_agent_config()
        self.root = tk.Tk()
        self.root.title("Desktop Agent")
        self.root.geometry("810x145+40+40")
        self.root.resizable(True, False)
        self.root.attributes("-topmost", True)

        self.entry = tk.Entry(
            self.root,
            font=("Microsoft YaHei UI", 15),
            relief="flat",
            borderwidth=10,
        )
        self.entry.pack(fill="x", padx=10, pady=(10, 5))
        self.entry.insert(0, PLACEHOLDER)
        self.entry.configure(fg="#777777")
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._restore_placeholder)
        self.entry.bind("<Return>", self._submit)
        self.entry.bind("<Escape>", self._clear)

        self.settings = tk.Frame(self.root)
        self.settings.pack(fill="x", padx=10, pady=(4, 10))
        self.steps_var = tk.IntVar(value=self.config.max_steps)
        self.operations_var = tk.IntVar(value=self.config.max_atomic_operations)
        self.confidence_var = tk.DoubleVar(value=self.config.min_confidence)
        self.grid_rows_var = tk.IntVar(value=self.config.grid_rows)
        self.grid_columns_var = tk.IntVar(value=self.config.grid_columns)
        self.trust_var = tk.BooleanVar(value=self.config.full_trust)
        self._setting_controls: list[tk.Widget] = []

        self._add_spinbox("最大步数", self.steps_var, 1, 60, 1, 0)
        self._add_spinbox("原子操作", self.operations_var, 1, 100, 1, 2)
        self._add_spinbox("置信度", self.confidence_var, 0, 1, 0.05, 4, width=5)
        self._add_spinbox("网格行", self.grid_rows_var, 2, 20, 1, 6)
        self._add_spinbox("网格列", self.grid_columns_var, 2, 20, 1, 8)
        trust = tk.Checkbutton(
            self.settings,
            text="完全信任",
            variable=self.trust_var,
            takefocus=False,
        )
        trust.grid(row=0, column=10, padx=(12, 0), sticky="w")
        self._setting_controls.append(trust)
        self.stop_button = tk.Button(
            self.settings,
            text="终止",
            command=self._stop,
            state="disabled",
            fg="#ffffff",
            bg="#c62828",
            activebackground="#a51f1f",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
        )
        self.stop_button.grid(row=0, column=11, padx=(12, 0), sticky="e")

        self._busy = False
        self._active_agent: DesktopAgent | None = None
        self._active_task_id: str | None = None
        self._results: queue.Queue[TaskResult | Exception] = queue.Queue()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll_result)
        self.root.after(150, self._focus_entry)

    def run(self) -> None:
        self.root.mainloop()

    def _submit(self, _event=None) -> str:
        if self._busy:
            return "break"
        task_text = self.entry.get().strip()
        if not task_text or task_text == PLACEHOLDER:
            self.root.bell()
            return "break"

        try:
            task_config = replace(
                self.config,
                max_steps=int(self.steps_var.get()),
                max_atomic_operations=int(self.operations_var.get()),
                min_confidence=float(self.confidence_var.get()),
                grid_rows=int(self.grid_rows_var.get()),
                grid_columns=int(self.grid_columns_var.get()),
                full_trust=bool(self.trust_var.get()),
            )
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc), parent=self.root)
            return "break"

        agent = DesktopAgent(task_config)
        task = agent.create_general_task(task_text)
        review = agent.review(task)
        if review.decision == ReviewDecision.REJECT:
            messagebox.showerror("任务被拒绝", review.summary, parent=self.root)
            return "break"

        approved = task_config.full_trust
        if not approved:
            plan = "\n".join(
                f"{index}. {action.purpose}"
                for index, action in enumerate(review.actions, start=1)
            )
            parameter_text = (
                f"steps={task_config.max_steps}, "
                f"ops={task_config.max_atomic_operations}, "
                f"confidence={task_config.min_confidence:.2f}, "
                f"grid={task_config.grid_rows}x{task_config.grid_columns}"
            )
            approved = messagebox.askyesno(
                "任务审核",
                f"{review.summary}\n\n参数：{parameter_text}\n\n{plan}\n\n是否执行？",
                parent=self.root,
            )
        if not approved:
            agent.execute(task.id, approved=False)
            return "break"

        self._busy = True
        self._active_agent = agent
        self._active_task_id = task.id
        self.entry.configure(state="disabled")
        self._set_settings_state("disabled")
        self.stop_button.configure(state="normal")
        self.root.title("Desktop Agent — 执行中")
        # 保持窗口可见，但等待审核对话框完全消失后才开始截图。
        self.root.update_idletasks()
        self.root.after(400, self._start_execution, agent, task.id)
        return "break"

    def _start_execution(self, agent: DesktopAgent, task_id: str) -> None:
        threading.Thread(
            target=self._execute,
            args=(agent, task_id),
            daemon=True,
        ).start()

    def _execute(self, agent: DesktopAgent, task_id: str) -> None:
        try:
            self._results.put(agent.execute(task_id, approved=True))
        except Exception as exc:
            self._results.put(exc)

    def _poll_result(self) -> None:
        try:
            outcome = self._results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result)
            return

        self._busy = False
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.entry.configure(state="normal")
        self._set_settings_state("normal")
        self.stop_button.configure(state="disabled")
        self._active_agent = None
        self._active_task_id = None

        if isinstance(outcome, Exception):
            self.root.title("Desktop Agent — 执行异常")
            messagebox.showerror("执行异常", str(outcome), parent=self.root)
        elif outcome.status == TaskStatus.SUCCEEDED:
            self.root.title("Desktop Agent — 已完成")
            self.entry.delete(0, tk.END)
        elif outcome.status == TaskStatus.CANCELLED:
            self.root.title("Desktop Agent — 已终止")
        else:
            self.root.title("Desktop Agent — 执行失败")
            messagebox.showerror(
                "任务失败",
                outcome.error or outcome.status.value,
                parent=self.root,
            )
        self._focus_entry()
        self.root.after(100, self._poll_result)

    def _clear_placeholder(self, _event=None) -> None:
        if self.entry.get() == PLACEHOLDER:
            self.entry.delete(0, tk.END)
            self.entry.configure(fg="#111111")

    def _restore_placeholder(self, _event=None) -> None:
        if not self.entry.get().strip() and not self._busy:
            self.entry.insert(0, PLACEHOLDER)
            self.entry.configure(fg="#777777")

    def _clear(self, _event=None) -> str:
        if not self._busy:
            self.entry.delete(0, tk.END)
            self.entry.configure(fg="#111111")
        return "break"

    def _focus_entry(self) -> None:
        self.entry.focus_force()

    def _stop(self) -> None:
        if not self._busy or self._active_agent is None or self._active_task_id is None:
            return
        if self._active_agent.cancel(self._active_task_id):
            self.root.title("Desktop Agent — 正在终止")
            self.stop_button.configure(state="disabled")

    def _close(self) -> None:
        if self._busy and self._active_agent is not None and self._active_task_id is not None:
            self._active_agent.cancel(self._active_task_id)
        self.root.destroy()

    def _add_spinbox(
        self,
        label: str,
        variable,
        from_: float,
        to: float,
        increment: float,
        column: int,
        *,
        width: int = 4,
    ) -> None:
        tk.Label(self.settings, text=label).grid(row=0, column=column, sticky="e")
        spinbox = tk.Spinbox(
            self.settings,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
            width=width,
        )
        spinbox.grid(row=0, column=column + 1, padx=(4, 10), sticky="w")
        self._setting_controls.append(spinbox)

    def _set_settings_state(self, state: str) -> None:
        for control in self._setting_controls:
            control.configure(state=state)


if __name__ == "__main__":
    DesktopAgentWindow().run()
