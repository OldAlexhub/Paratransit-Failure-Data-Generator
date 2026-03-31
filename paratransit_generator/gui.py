from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .exporter import export_to_csv, export_to_excel
from .generator import ParatransitDataGenerator
from .models import GeneratedData, ScenarioInput


class ParatransitGeneratorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Paratransit Failure Data Generator")
        self.root.geometry("1320x780")
        self.root.minsize(1080, 640)
        self.icon_image: tk.PhotoImage | None = None

        self.generator = ParatransitDataGenerator()
        self.generated_data: GeneratedData | None = None
        self.preview_limit = 200
        self.treeviews: dict[str, ttk.Treeview] = {}
        self.targets_text: tk.Text | None = None

        self.start_date_var = tk.StringVar(value=(date.today() - timedelta(days=29)).isoformat())
        self.end_date_var = tk.StringVar(value=date.today().isoformat())
        self.record_count_var = tk.StringVar(value="500")
        self.status_var = tk.StringVar(value="Enter a date range and record count, then generate a new scenario.")

        self._apply_window_icon()
        self._build_ui()

    def _apply_window_icon(self) -> None:
        icon_path = Path(__file__).resolve().parent.parent / "logo-icon.png"
        if not icon_path.exists():
            return
        try:
            self.icon_image = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill="x")
        for column in (1, 3, 5):
            controls.columnconfigure(column, weight=1)

        ttk.Label(controls, text="Start date (YYYY-MM-DD)").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 10))
        ttk.Entry(controls, textvariable=self.start_date_var, width=16).grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(0, 10))
        ttk.Label(controls, text="End date (YYYY-MM-DD)").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=(0, 10))
        ttk.Entry(controls, textvariable=self.end_date_var, width=16).grid(row=0, column=3, sticky="ew", padx=(0, 16), pady=(0, 10))
        ttk.Label(controls, text="Number of records").grid(row=0, column=4, sticky="w", padx=(0, 8), pady=(0, 10))
        ttk.Entry(controls, textvariable=self.record_count_var, width=14).grid(row=0, column=5, sticky="ew", pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(0, 12))
        ttk.Button(buttons, text="Generate", command=self.generate_data).pack(side="left")
        self.export_csv_button = ttk.Button(buttons, text="Export CSV", command=self.export_csv, state="disabled")
        self.export_csv_button.pack(side="left", padx=(8, 0))
        self.export_excel_button = ttk.Button(buttons, text="Export Excel", command=self.export_excel, state="disabled")
        self.export_excel_button.pack(side="left", padx=(8, 0))

        ttk.Label(
            outer,
            text=(
                "Preview shows the first 200 rows from each generated raw dataset. "
                "The record count controls trip rows; related run, driver, vehicle, dispatch, and complaint rows are derived from those trips. "
                "The sidebar shows the embedded deficiencies for the current scenario only and is not exported."
            ),
            wraplength=1200,
            justify="left",
        ).pack(fill="x", pady=(0, 12))

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=0)
        content.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(content)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        for dataset_name in ("trips", "runs", "drivers", "vehicles", "dispatch_events", "complaints"):
            self._build_tab(dataset_name)

        sidebar = ttk.LabelFrame(content, text="Identify These Deficiencies", padding=12)
        sidebar.grid(row=0, column=1, sticky="ns")
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)
        ttk.Label(
            sidebar,
            text="For the current dataset, use the raw files to identify the following embedded issues:",
            wraplength=280,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.targets_text = tk.Text(sidebar, width=36, height=26, wrap="word", relief="flat", borderwidth=0)
        self.targets_text.grid(row=1, column=0, sticky="nsew")
        self.targets_text.insert("1.0", "Generate a scenario to populate this list.")
        self.targets_text.configure(state="disabled")

        ttk.Label(outer, textvariable=self.status_var, anchor="w").pack(fill="x", pady=(12, 0))

    def _build_tab(self, dataset_name: str) -> None:
        frame = ttk.Frame(self.notebook, padding=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.notebook.add(frame, text=dataset_name.title().replace("_", " "))

        tree = ttk.Treeview(frame, show="headings")
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.treeviews[dataset_name] = tree

    def generate_data(self) -> None:
        try:
            scenario_input = ScenarioInput(
                start_date=date.fromisoformat(self.start_date_var.get().strip()),
                end_date=date.fromisoformat(self.end_date_var.get().strip()),
                trip_count=int(self.record_count_var.get().strip()),
            )
            scenario_input.validate()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self.status_var.set("Generating synthetic operational failure data...")
        self.root.update_idletasks()
        try:
            self.generated_data = self.generator.generate(scenario_input)
        except Exception as exc:
            self.status_var.set("Generation failed.")
            messagebox.showerror("Generation failed", str(exc))
            return

        self._populate_previews(self.generated_data)
        self._populate_analysis_targets(self.generated_data)
        self.export_csv_button.config(state="normal")
        self.export_excel_button.config(state="normal")
        self.status_var.set(
            f"Generated {len(self.generated_data.trips):,} trips from {scenario_input.start_date.isoformat()} to {scenario_input.end_date.isoformat()}. "
            f"Previewing up to {self.preview_limit} rows per dataset."
        )

    def _populate_previews(self, generated_data: GeneratedData) -> None:
        for tab_index, (dataset_name, dataframe) in enumerate(generated_data.dataframes.items()):
            preview = dataframe.head(self.preview_limit).fillna("")
            tree = self.treeviews[dataset_name]
            tree.delete(*tree.get_children())
            columns = list(preview.columns)
            tree["columns"] = columns
            for column in columns:
                tree.heading(column, text=column)
                width = 110
                if column.endswith("_time") or column.endswith("_timestamp") or column in {"action_taken", "driver_name"}:
                    width = 170
                if column in {"trip_id", "run_id", "driver_id", "vehicle_id", "complaint_id", "event_id"}:
                    width = 135
                tree.column(column, width=width, minwidth=90, anchor="w", stretch=False)
            for row in preview.itertuples(index=False, name=None):
                tree.insert("", "end", values=[self._display_value(value) for value in row])
            self.notebook.tab(tab_index, text=f"{dataset_name.title().replace('_', ' ')} ({len(dataframe):,})")

    def _populate_analysis_targets(self, generated_data: GeneratedData) -> None:
        if not self.targets_text:
            return
        lines = [f"{index}. {target}" for index, target in enumerate(generated_data.analysis_targets, start=1)]
        lines.append("")
        lines.append(f"Scenario seed: {generated_data.seed}")
        lines.append(f"Generated at: {generated_data.generated_at.isoformat(sep=' ')}")
        self.targets_text.configure(state="normal")
        self.targets_text.delete("1.0", "end")
        self.targets_text.insert("1.0", "\n".join(lines))
        self.targets_text.configure(state="disabled")

    def _display_value(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.2f}" if abs(value - round(value)) > 0.001 else str(int(round(value)))
        return str(value)

    def export_csv(self) -> None:
        if not self.generated_data:
            return
        target_directory = filedialog.askdirectory(title="Choose CSV export folder")
        if not target_directory:
            return
        try:
            export_to_csv(self.generated_data, target_directory)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.status_var.set(f"Exported CSV files to {Path(target_directory)}")

    def export_excel(self) -> None:
        if not self.generated_data:
            return
        target_file = filedialog.asksaveasfilename(
            title="Save Excel workbook",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not target_file:
            return
        try:
            export_to_excel(self.generated_data, target_file)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.status_var.set(f"Exported Excel workbook to {Path(target_file)}")


def launch_app() -> None:
    root = tk.Tk()
    app = ParatransitGeneratorApp(root)
    app.root.mainloop()
