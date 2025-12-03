"""
eyelocater_gui_qt.py

Simple Qt GUI wrapper around eyelocater_core.run_annotation_with_info
"""

import difflib
import sys
from pathlib import Path
import signal
import stereo as st
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QComboBox,
    QCheckBox,
    QTextEdit,
    QLabel,
    QHBoxLayout,
    QMessageBox,
    QRadioButton,
    QButtonGroup,
    QSizePolicy
)

from eyelocater_core import (
    AnnotationConfig,
    run_annotation_with_info,
    AnnotationError,
)

MAX_PREVIEW_LEN = 60
BUTTON_WIDTH = 70

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._gene_index = None  # type: set[str] | None
        self.setWindowTitle("Eyelocater")
        self.resize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # --------- Top form (parameters) ---------
        form_layout = QFormLayout()

        # Reference h5ad
        self.ref_edit = QLineEdit()
        ref_btn = QPushButton("Browse…")
        ref_btn.clicked.connect(self.browse_ref)
        ref_row = QHBoxLayout()
        ref_row.addWidget(self.ref_edit)
        ref_row.addWidget(ref_btn)
        form_layout.addRow("Reference h5ad:", ref_row)

        # Reference column
        self.ref_col_combo = QComboBox()
        self.ref_col_combo.setEditable(False)
        form_layout.addRow("Reference column:", self.ref_col_combo)

        # Main data h5ad
        self.main_edit = QLineEdit()
        self.main_edit.setText("data/DR_only_stereo.h5ad")
        main_btn = QPushButton("Browse…")
        main_btn.clicked.connect(self.browse_main)
        main_row = QHBoxLayout()
        main_row.addWidget(self.main_edit)
        main_row.addWidget(main_btn)
        form_layout.addRow("Main Stereo h5ad:", main_row)

        self.region_defaults = {
            "eye": {
                "cell": "cluster_scatter_eye.pdf",
                "gene": "spatial_scatter_eye_*.pdf",
            },
            "retina": {
                "cell": "cluster_scatter_retina.pdf",
                "gene": "spatial_scatter_retina_*.pdf",
            },
            "cornea": {
                "cell": "cluster_scatter_cornea.pdf",
                "gene": "spatial_scatter_cornea_*.pdf",
            },
        }
        self._current_region = "eye"


        # Region
        # Region radios
        self.region_group = QButtonGroup(self)
        self.region_buttons = {}
        region_layout = QHBoxLayout()
        region_layout.setContentsMargins(0, 0, 0, 0)
        region_layout.setSpacing(12)  # 控制按钮之间的间隔（自己调）

        for i, name in enumerate(["eye", "retina", "cornea"]):
            btn = QRadioButton(name)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(BUTTON_WIDTH)
            btn.setMaximumWidth(BUTTON_WIDTH)
            if name == "eye":
                btn.setChecked(True)

            self.region_group.addButton(btn, i)
            self.region_buttons[name] = btn
            region_layout.addWidget(btn)
        self.region_group.buttonToggled.connect(self.on_region_toggled)
        form_layout.addRow("Region:", region_layout)
        self.highlight_region("eye")

        # Plot type radios
        self.plot_type_group = QButtonGroup(self)
        self.plot_type_buttons = {}
        plot_layout = QHBoxLayout()
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(12)

        for i, key in enumerate(["cell", "gene", "both"]):
            label = key.capitalize()
            btn = QRadioButton(label)
            btn.setProperty("plotType", key)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(BUTTON_WIDTH)
            btn.setMaximumWidth(BUTTON_WIDTH)
            if key == "cell":
                btn.setChecked(True)

            self.plot_type_group.addButton(btn, i)
            self.plot_type_buttons[key] = btn
            plot_layout.addWidget(btn)
        form_layout.addRow("Plot type:", plot_layout)
        self.highlight_plot_type("cell")
        self.plot_type_group.buttonToggled.connect(self.on_plot_type_toggled)

        # Method (GPU/CPU)
        self.method_combo = QComboBox()
        self.method_combo.addItems([
            "Auto (GPU → CPU)",  # rapids with fallback
            "CPU only",
        ])
        form_layout.addRow("Backend:", self.method_combo)

        # Gene(s)
        self.gene_edit = QLineEdit()
        self.gene_edit.setPlaceholderText("Rho or Rho,Opn1mw,Opn1sw")
        form_layout.addRow("Gene(s):", self.gene_edit)
        self.gene_edit.textChanged.connect(self.on_gene_text_changed)

        # Output PDF for cell plot
        self.out_edit = QLineEdit()
        self.out_edit.setText(self.region_defaults["eye"]["cell"])
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit)
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(self.browse_cell_output)
        out_row.addWidget(out_btn)
        form_layout.addRow("Cell plot output:", out_row)

        # Output pattern for gene plots
        self.gene_out_edit = QLineEdit()
        self.gene_out_edit.setText(self.region_defaults["eye"]["gene"])
        self.gene_out_edit.setPlaceholderText(self.region_defaults["eye"]["gene"])
        gene_out_row = QHBoxLayout()
        gene_out_row.addWidget(self.gene_out_edit)
        gene_out_btn = QPushButton("Browse…")
        gene_out_btn.clicked.connect(self.browse_gene_output)
        gene_out_row.addWidget(gene_out_btn)
        self.gene_out_hint = QLabel(
            "'*' will be replaced by the gene name, e.g. spatial_scatter_Rho.pdf.\n"
            "WARNING: existing files may be overwritten when using '*', without any warning from the file browser."
        )
        self.gene_out_hint.setStyleSheet("color: gray;")
        self.gene_out_hint.setWordWrap(True)

        gene_out_container = QWidget()
        gene_out_layout = QVBoxLayout(gene_out_container)
        gene_out_layout.setContentsMargins(0, 0, 0, 0)
        gene_out_layout.setSpacing(2)
        gene_out_layout.addLayout(gene_out_row)
        gene_out_layout.addWidget(self.gene_out_hint)

        form_layout.addRow("Gene plot output:", gene_out_container)

        # Options
        self.show_plot_check = QCheckBox("Show matplotlib windows")
        self.show_plot_check.setChecked(False)
        self.suppress_warn_check = QCheckBox("Suppress Python warnings")
        self.suppress_warn_check.setChecked(True)
        form_layout.addRow("", self.show_plot_check)
        form_layout.addRow("", self.suppress_warn_check)

        main_layout.addLayout(form_layout)

        # --------- Run button + status ---------
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run annotation")
        self.run_btn.clicked.connect(self.run_annotation_clicked)
        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        btn_row.addWidget(self.run_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.status_label)

        main_layout.addLayout(btn_row)

        # --------- Log output ---------
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText(
            "Logs will appear here (methods used, warnings, errors)…"
        )
        main_layout.addWidget(self.log_edit, stretch=1)
        self.update_plot_output_enable()

    # --------- Browse helpers ---------
    def highlight_region(self, region_name: str):
        """高亮当前 region（比如自动检测出来时）。"""
        for name, btn in self.region_buttons.items():
            if name == region_name:
                btn.setStyleSheet("font-weight: 600; color: #007acc;")
            else:
                btn.setStyleSheet("")

    def highlight_plot_type(self, plot_type: str):
        for name, btn in self.plot_type_buttons.items():
            if name == plot_type:
                btn.setStyleSheet("font-weight: 600; color: #007acc;")
            else:
                btn.setStyleSheet("")

    def get_region(self) -> str:
        btn = self.region_group.checkedButton()
        if not btn:
            return "eye"
        return btn.text()

    def on_region_toggled(self, button, checked):
        if not checked:
            return
        new_region = button.text()
        self.highlight_region(new_region)
        self.update_output_filenames_for_region(new_region)



    def on_plot_type_toggled(self, button, checked):
        if checked:
            plot_type = button.property("plotType")
            self.highlight_plot_type(plot_type)
            self.update_plot_output_enable()

    def browse_ref(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select reference h5ad",
            "",
            "H5AD files (*.h5ad);;All files (*)",
        )
        if path:
            self.ref_edit.setText(path)
            self.load_ref_columns(path)

    def browse_main(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select main Stereo h5ad",
            "",
            "H5AD files (*.h5ad);;All files (*)",
        )
        if path:
            self.main_edit.setText(path)

    def update_output_filenames_for_region(self, new_region: str):
        """当 Region 改变时，根据默认命名规则智能更新输出文件名。"""
        prev_region = getattr(self, "_current_region", None)
        if prev_region is None or prev_region == new_region:
            self._current_region = new_region
            return

        prev_defs = self.region_defaults.get(prev_region, {})
        new_defs = self.region_defaults.get(new_region, {})

        # ---- Cell plot output ----
        current_cell = self.out_edit.text().strip()
        if current_cell:
            cell_path = Path(current_cell)
            prev_default_name = prev_defs.get("cell")
            new_default_name = new_defs.get("cell", cell_path.name)
            if prev_default_name and cell_path.name == prev_default_name:
                self.out_edit.setText(str(cell_path.with_name(new_default_name)))
        else:
            self.out_edit.setText(new_defs.get("cell", ""))

        # ---- Gene plot output ----
        current_gene = self.gene_out_edit.text().strip()
        if current_gene:
            gene_path = Path(current_gene)
            prev_default_gene = prev_defs.get("gene")
            new_default_gene = new_defs.get("gene", gene_path.name)

            if prev_default_gene and gene_path.name == prev_default_gene:
                self.gene_out_edit.setText(str(gene_path.with_name(new_default_gene)))
                self.gene_out_edit.setPlaceholderText(new_defs.get("gene", ""))
        else:
            self.gene_out_edit.setText(new_defs.get("gene", ""))
            self.gene_out_edit.setPlaceholderText(new_defs.get("gene", ""))

        self._current_region = new_region

    def browse_cell_output(self):
        """
        选择 cell 图的输出文件。
        - 用当前文本里的目录/文件名作为默认值
        - 如果没写后缀，就自动加 .pdf
        """
        current = self.out_edit.text().strip() or "cluster_scatter_output.pdf"
        p = Path(current)

        # 初始目录 / 文件名
        if p.is_absolute():
            initial_dir = str(p.parent)
            initial_name = p.name
        else:
            # 相对路径：如果有父目录，用它；否则用当前工作目录
            initial_dir = str(p.parent) if str(p.parent) not in ("", ".") else ""
            initial_name = p.name or "cluster_scatter_output.pdf"

        dialog_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select cell plot output",
            str(Path(initial_dir) / initial_name),
            "PDF files (*.pdf);;All files (*)",
        )
        if dialog_path:
            # 没有 .pdf 后缀的话自动补一个
            if not dialog_path.lower().endswith(".pdf"):
                dialog_path += ".pdf"
            self.out_edit.setText(dialog_path)

    def browse_gene_output(self):
        current = self.gene_out_edit.text().strip() or "spatial_scatter_*.pdf"
        p = Path(current)

        if p.is_absolute():
            initial_dir = str(p.parent)
            initial_name = p.name
        else:
            initial_dir = str(p.parent) if str(p.parent) not in ("", ".") else ""
            initial_name = p.name or "spatial_scatter_*.pdf"

        dialog_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select gene plot output",
            str(Path(initial_dir) / initial_name),
            "PDF files (*.pdf);;All files (*)",
        )
        if dialog_path:
            if not dialog_path.lower().endswith(".pdf"):
                dialog_path += ".pdf"
            self.gene_out_edit.setText(dialog_path)

    def load_ref_columns(self, path: str):
        """读取 ref h5ad 的 obs 列名，填充到下拉框，并预览前几项（预览用斜体）。"""
        self.ref_col_combo.clear()
        try:
            ref = st.io.read_h5ad(path)
            adata = getattr(ref, "adata", None)
            if adata is None:
                raise RuntimeError("Reference does not contain AnnData (adata).")

            obs = adata.obs
            cols = list(obs.columns)

            for col in cols:
                raw_vals = list(map(str, obs[col].unique()[:5]))
                full_preview = ", ".join(raw_vals)  # 完整字符串（用于 tooltip）

                preview_parts = []
                for v in raw_vals:
                    if not preview_parts:
                        tentative = v
                    else:
                        tentative = ", ".join(preview_parts + [v])

                    if len(tentative) > MAX_PREVIEW_LEN:
                        break
                    preview_parts.append(v)
                if preview_parts:
                    preview = ", ".join(preview_parts)
                    if len(preview_parts) < len(raw_vals):
                        preview += ", ..."
                else:
                    preview = ""

                if preview:
                    display_text = f'{col} : e.g. {preview}'
                else:
                    display_text = col

                idx = self.ref_col_combo.count()
                # 显示富文本，userData 保存真正的列名
                self.ref_col_combo.addItem(display_text, userData=col)

                # tooltip 显示完整未截断的 preview（纯文本就够了）
                if full_preview:
                    self.ref_col_combo.setItemData(
                        idx,
                        f"{col}: {full_preview}",
                        Qt.ItemDataRole.ToolTipRole,
                    )

            # 自动选一个最接近 "celltype" 的列
            best_idx = self._pick_best_ref_col(cols)
            if best_idx is not None and best_idx < self.ref_col_combo.count():
                self.ref_col_combo.setCurrentIndex(best_idx)

        except Exception as e:
            QMessageBox.warning(
                self,
                "Reference error",
                f"Failed to inspect reference file:\n{e}",
            )

    def _load_gene_index(self):
        if self._gene_index is not None:
            return

        path = self.main_edit.text().strip()
        if not path or not Path(path).exists():
            return  # 让 run 时的文件检查去报错

        try:
            data = st.io.read_stereo_h5ad(path)
            self._gene_index = set(map(str, data.gene_names))
        except Exception as e:
            # 不阻止运行；真正的错误会在 backend 再报一次
            self.append_log(f"[WARN] Could not load gene list: {e}")

    def _pick_best_ref_col(self, cols):
        """找一个最像 celltype 的列名。"""
        if not cols:
            return None
        target = "celltype"
        for i, c in enumerate(cols):
            if c == target or c.lower() == target:
                return i
        for i, c in enumerate(cols):
            if target in c.lower():
                return i
        match = difflib.get_close_matches(target, cols, n=1, cutoff=0.4)
        if match:
            return cols.index(match[0])

        return 0

    # --------- GUI -------------
    def set_plot_type(self, key: str):
        """key in {'cell','gene','both'}."""
        for btn in self.plot_type_buttons.values():
            if btn.property("plotType") == key:
                btn.setChecked(True)
                break

    def get_plot_type(self) -> str:
        btn = self.plot_type_group.checkedButton()
        if not btn:
            return "cell"
        return btn.property("plotType") or "cell"

    def on_gene_text_changed(self, text: str):
        text = text.strip()
        if text:
            # 有基因 → 自动选 both
            if self.get_plot_type() == 'cell':
                self.set_plot_type("both")
        else:
            # 没基因 → 如果当前是 gene/both，就退回 cell
            if self.get_plot_type() in ("gene", "both"):
                self.set_plot_type("cell")
        self.update_plot_output_enable()

    # --------- Core run ---------

    def append_log(self, text: str):
        self.log_edit.append(text)
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def update_plot_output_enable(self):
        plot_type = self.get_plot_type()
        if plot_type == "cell":
            self.out_edit.setEnabled(True)
            self.gene_out_edit.setEnabled(False)
        elif plot_type == "gene":
            self.out_edit.setEnabled(False)
            self.gene_out_edit.setEnabled(True)
        else:  # both
            self.out_edit.setEnabled(True)
            self.gene_out_edit.setEnabled(True)

    def run_annotation_clicked(self):
        ref_path = self.ref_edit.text().strip()
        main_path = self.main_edit.text().strip()
        ref_col = self.ref_col_combo.currentData()

        # Basic validation
        if not ref_path or not Path(ref_path).exists():
            QMessageBox.warning(self, "Error", "Please select a valid reference h5ad file.")
            return
        if not main_path or not Path(main_path).exists():
            QMessageBox.warning(self, "Error", "Please select a valid main Stereo h5ad file.")
            return
        if not ref_col:
            QMessageBox.warning(self, "Error", "Please provide the reference column name.")
            return

        region = self.get_region()
        plot_type = self.get_plot_type()
        genes_str = self.gene_edit.text().strip()
        if plot_type in ("gene", "both") and not genes_str:
            QMessageBox.warning(
                self,
                "Missing gene",
                "Plot type is 'gene' or 'both', but no gene name(s) were provided.",
            )
            return
        genes = genes_str or None
        out_pdf = self.out_edit.text().strip() or "cluster_scatter_output.pdf"
        gene_out = self.gene_out_edit.text().strip() or "spatial_scatter_*.pdf"

        # Method mapping
        method_ui = self.method_combo.currentText()
        if method_ui.startswith("Auto"):
            method = "rapids"  # GPU 优先 + fallback
        else:
            method = "cpu"
        self._load_gene_index()
        genes_str = self.gene_edit.text().strip()
        genes = genes_str or None

        if self._gene_index and genes:
            # 用和 backend 一样的规则拆 gene list
            import re as _re
            parts = _re.split(r"[;,]", genes_str)
            cleaned = [p.strip() for p in parts if p.strip()]
            invalid = [g for g in cleaned if g not in self._gene_index]

            if invalid:
                # 给用户一个明确提示，再决定要不要直接 return
                QMessageBox.warning(
                    self,
                    "Unknown genes",
                    f"The following genes were not found in this dataset:\n"
                    f"{', '.join(invalid)}",
                )
                return

        config = AnnotationConfig(
            ref_path=ref_path,
            ref_used_col=ref_col,
            data_region=region,  # "eye" / "retina" / "cornea"
            main_data_path=main_path,
            out_pdf=out_pdf,
            method=method,
            show_plot=self.show_plot_check.isChecked(),
            suppress_warnings=self.suppress_warn_check.isChecked(),
            gene=genes,
            plot_type=plot_type,  # "cell" / "gene" / "both"
            gene_out_pattern=gene_out
        )

        self.run_btn.setEnabled(False)
        self.status_label.setText("Running annotation…")
        QApplication.processEvents()

        self.append_log("==== New run ====")
        self.append_log(f"Ref: {ref_path}")
        self.append_log(f"Main: {main_path}")
        self.append_log(f"Region: {region}, Method preference: {method}")
        if genes:
            self.append_log(f"Genes: {genes}")
        self.append_log(f"Plot type: {plot_type}")
        self.append_log("Starting…")

        try:
            # 这里会在 stdout 打出 Eyelocater 的 log（GPU/CPU），
            # 当前版本我们没重定向 stdout，但信息至少在终端可见。
            _, method_used, plot_files = run_annotation_with_info(config)

            self.append_log(f"Done. Method used: {method_used!r}")
            if plot_files.get("cell"):
                self.append_log(f"Cell plots: {plot_files['cell']}")
            if plot_files.get("gene"):
                self.append_log(f"Gene plots: {plot_files['gene']}")

            self.status_label.setText(f"Finished (method={method_used}).")
        except AnnotationError as e:
            self.append_log(f"[AnnotationError] {e}")
            QMessageBox.critical(self, "Annotation error", str(e))
            self.status_label.setText("Error.")
        except Exception as e:
            self.append_log(f"[Unexpected error] {e}")
            QMessageBox.critical(self, "Unexpected error", str(e))
            self.status_label.setText("Error.")
        finally:
            self.run_btn.setEnabled(True)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
