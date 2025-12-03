# eyelocater_gui_qt.py

import sys
import os

# --- Step 1: 绝对优先设置 Matplotlib 后端 ---
import matplotlib

matplotlib.use('Agg')

# --- Step 2: 导入业务库 ---
import stereo as st
from eyelocater_core import (
    AnnotationConfig,
    run_annotation_with_info,
)

# --- Step 3: 清除 OpenCV 环境污染 ---
if 'QT_QPA_PLATFORM_PLUGIN_PATH' in os.environ:
    os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH')

# --- Step 4: 导入 UI 库 ---
import signal
import gc
import difflib
from pathlib import Path
import platform
import subprocess

from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QComboBox, QCheckBox,
    QTextEdit, QLabel, QHBoxLayout, QMessageBox, QRadioButton,
    QButtonGroup, QProgressBar, QSizePolicy, QGroupBox, QStackedLayout
)

# --- 常量定义 ---
BUTTON_WIDTH = 70


class StreamRedirector(QObject):
    text_written = Signal(str)

    def write(self, text):
        self.text_written.emit(str(text))

    def flush(self):
        pass


class Worker(QThread):
    finished_signal = Signal(object, str, dict)
    error_signal = Signal(str)

    def __init__(self, config: AnnotationConfig):
        super().__init__()
        self.config = config

    def run(self):
        try:
            data, method, files = run_annotation_with_info(self.config)
            self.finished_signal.emit(data, method, files)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_signal.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Eyelocater GUI")
        self.resize(950, 720)

        # --- 缓存 ---
        self.cached_main_data = None
        self.cached_main_path = None
        self.cached_ref_data = None
        self.cached_ref_path = None

        self.worker = None

        self.region_defaults = {
            "eye": {"cell": "cluster_scatter_eye.pdf", "gene": "spatial_scatter_eye_*.pdf"},
            "retina": {"cell": "cluster_scatter_retina.pdf", "gene": "spatial_scatter_retina_*.pdf"},
            "cornea": {"cell": "cluster_scatter_cornea.pdf", "gene": "spatial_scatter_cornea_*.pdf"},
        }
        self._current_region = "eye"
        self._user_touched_pdf_option = False
        self._init_ui()
        self._setup_logging()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # 1. 配置区容器
        self.input_container = QGroupBox("Configuration")
        form_layout = QFormLayout(self.input_container)

        # Ref Path
        self.ref_edit = QLineEdit()
        self.ref_btn = QPushButton("Browse…")
        self.ref_btn.clicked.connect(self.browse_ref)
        l_ref = QHBoxLayout()
        l_ref.addWidget(self.ref_edit)
        l_ref.addWidget(self.ref_btn)
        form_layout.addRow("Reference h5ad:", l_ref)

        # Ref Column
        self.ref_col_combo = QComboBox()
        self.ref_col_combo.setEditable(True)
        form_layout.addRow("Reference column:", self.ref_col_combo)

        # Main Data Path
        self.main_edit = QLineEdit("data/DR_only_stereo.h5ad")
        self.main_btn = QPushButton("Browse…")
        self.main_btn.clicked.connect(self.browse_main)
        l_main = QHBoxLayout()
        l_main.addWidget(self.main_edit)
        l_main.addWidget(self.main_btn)
        form_layout.addRow("Main Stereo h5ad:", l_main)

        # Region
        self.region_group = QButtonGroup(self)
        self.region_buttons = {}
        self.region_layout = QHBoxLayout()
        self.region_layout.setSpacing(12)
        for i, name in enumerate(["eye", "retina", "cornea"]):
            btn = QRadioButton(name)
            btn.setFixedSize(BUTTON_WIDTH, 25)
            if name == "eye": btn.setChecked(True)
            self.region_group.addButton(btn, i)
            self.region_layout.addWidget(btn)
            self.region_buttons[name] = btn
        self.region_layout.addStretch()
        self.region_group.buttonToggled.connect(self.on_region_toggled)
        self.highlight_region("eye")
        form_layout.addRow("Region:", self.region_layout)

        # Plot Type
        self.plot_group = QButtonGroup(self)
        self.plot_buttons = {}
        plot_layout = QHBoxLayout()
        plot_layout.setSpacing(12)
        for i, key in enumerate(["cell", "gene", "both"]):
            btn = QRadioButton(key.capitalize())
            btn.setProperty("plotType", key)
            btn.setFixedSize(BUTTON_WIDTH, 25)
            if key == "cell": btn.setChecked(True)
            self.plot_group.addButton(btn, i)
            plot_layout.addWidget(btn)
            self.plot_buttons[key] = btn
        plot_layout.addStretch()
        self.plot_group.buttonToggled.connect(self.on_plot_type_toggled)
        self.highlight_plot_type("cell")
        form_layout.addRow("Plot type:", plot_layout)

        # Backend
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Auto (GPU → CPU)", "CPU only"])
        form_layout.addRow("Backend:", self.method_combo)

        # Genes
        self.gene_edit = QLineEdit()
        self.gene_edit.setPlaceholderText("Rho or Rho, Opn1mw")
        self.gene_edit.textChanged.connect(self.on_gene_changed)
        form_layout.addRow("Gene(s):", self.gene_edit)

        # Outputs
        self.out_cell_edit = QLineEdit(self.region_defaults["eye"]["cell"])
        self.out_cell_btn = QPushButton("Browse…")
        self.out_cell_btn.clicked.connect(self.browse_cell_output)
        l_out_cell = QHBoxLayout()
        l_out_cell.addWidget(self.out_cell_edit)
        l_out_cell.addWidget(self.out_cell_btn)
        form_layout.addRow("Cell plot output:", l_out_cell)

        self.out_gene_edit = QLineEdit(self.region_defaults["eye"]["gene"])
        self.out_gene_btn = QPushButton("Browse…")
        self.out_gene_btn.clicked.connect(self.browse_gene_output)
        l_out_gene = QHBoxLayout()
        l_out_gene.addWidget(self.out_gene_edit)
        l_out_gene.addWidget(self.out_gene_btn)

        self.gene_out_hint = QLabel(
            "'*' acts as wildcard for gene names.\n"
            "⚠️ Note: File browser may not warn about overwriting when using wildcards."
        )
        self.gene_out_hint.setStyleSheet("color: gray;")

        c_gene = QWidget()
        v_gene = QVBoxLayout(c_gene)
        v_gene.setContentsMargins(0, 0, 0, 0)
        v_gene.addLayout(l_out_gene)
        v_gene.addWidget(self.gene_out_hint)
        form_layout.addRow("Gene plot output:", c_gene)

        self.open_pdf_check = QCheckBox("Open PDF after run")
        self.open_pdf_check.clicked.connect(lambda: setattr(self, '_user_touched_pdf_option', True))
        form_layout.addRow("", self.open_pdf_check)

        main_layout.addWidget(self.input_container)

        # 2. 运行控制区 (使用 StackedLayout 实现按钮变进度条)
        ctl_container = QWidget()
        self.btn_stack = QStackedLayout(ctl_container)
        self.btn_stack.setStackingMode(QStackedLayout.StackingMode.StackOne)  # 一次只显示一个

        # --- 页面 0: 正常的运行按钮 ---
        self.run_btn = QPushButton("Run Annotation")
        self.run_btn.setFixedHeight(45)
        self.run_btn.setStyleSheet("""
                    QPushButton {
                        font-weight: bold; font-size: 14px; 
                        background-color: #007acc; color: white; 
                        border-radius: 4px;
                    }
                    QPushButton:hover { background-color: #005f9e; }
                    QPushButton:pressed { background-color: #004a80; }
                """)
        self.run_btn.clicked.connect(self.start_run)
        self.btn_stack.addWidget(self.run_btn)

        # --- 页面 1: 进度条 (更现代的蓝白配色) ---
        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(45)  # 保持和按钮一样高，防止界面跳动
        self.pbar.setRange(0, 0)  # Indeterminate 模式 (来回弹动)
        self.pbar.setTextVisible(True)
        self.pbar.setFormat("Running... Please wait")
        self.pbar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 【关键】不要设置 setStyleSheet！
        # 让操作系统 (Windows/macOS/Linux) 自己去画它，
        # 这样就能找回原本自带的光泽、斜纹动画或脉冲效果。

        self.btn_stack.addWidget(self.pbar)

        # 将这个包含 Stack 的容器加入主布局
        main_layout.addWidget(ctl_container)

        # 3. 日志区
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        main_layout.addWidget(self.log_edit)

        self.update_inputs_enable()

        self.update_inputs_enable()

    def _setup_logging(self):
        self.redirector = StreamRedirector()
        self.redirector.text_written.connect(self.append_log)
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = self.redirector
        sys.stderr = self.redirector

    def closeEvent(self, event):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        super().closeEvent(event)

    @Slot(str)
    def append_log(self, text):
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

    # --- UI 状态管理 ---
    def set_interface_locked(self, locked: bool):
        self.input_container.setEnabled(not locked)
        self.run_btn.setEnabled(not locked)
        if locked:
            self.run_btn.setText("Running... (Please wait)")
            self.run_btn.setStyleSheet("background-color: #666; color: white; border-radius: 4px;")
        else:
            self.run_btn.setText("Run Annotation")
            self.run_btn.setStyleSheet(
                "font-weight: bold; font-size: 14px; background-color: #007acc; color: white; border-radius: 4px;")

    # --- 高亮与逻辑 ---
    def highlight_region(self, region_name: str):
        for name, btn in self.region_buttons.items():
            if name == region_name:
                btn.setStyleSheet("font-weight: 600; color: #007acc;")
            else:
                btn.setStyleSheet("")

    def highlight_plot_type(self, ptype: str):
        for name, btn in self.plot_buttons.items():
            if name == ptype:
                btn.setStyleSheet("font-weight: 600; color: #007acc;")
            else:
                btn.setStyleSheet("")

    def on_region_toggled(self, button, checked):
        if not checked: return
        new_region = button.text()
        self.highlight_region(new_region)
        self.update_output_filenames_for_region(new_region)

    def on_plot_type_toggled(self, button, checked):
        if not checked: return
        ptype = button.property("plotType")
        self.highlight_plot_type(ptype)
        self.update_inputs_enable()

        self._update_smart_pdf_check()

    def update_inputs_enable(self):
        ptype = self.plot_group.checkedButton().property("plotType")
        self.out_cell_edit.setEnabled(ptype in ["cell", "both"])
        self.out_cell_btn.setEnabled(ptype in ["cell", "both"])

        self.out_gene_edit.setEnabled(ptype in ["gene", "both"])
        self.out_gene_btn.setEnabled(ptype in ["gene", "both"])
        self.gene_out_hint.setEnabled(ptype in ["gene", "both"])

    def on_gene_changed(self, text):
        text = text.strip()
        if text:
            if self.plot_group.checkedButton().property("plotType") == "cell":
                for btn in self.plot_group.buttons():
                    if btn.property("plotType") == "both":
                        btn.setChecked(True)
                        break

        # 【新增】实时更新 PDF 选项状态
        self._update_smart_pdf_check()

    def _update_smart_pdf_check(self):
        """实时计算预计文件数量，智能控制 PDF 开关"""
        # 如果用户手动修改过设置，绝对不要干扰
        if self._user_touched_pdf_option:
            return

        ptype = self.plot_group.checkedButton().property("plotType")
        gene_text = self.gene_edit.text().strip()

        # 计算基因数量 (简单分割)
        import re
        if not gene_text:
            gene_count = 0
        else:
            # 兼容中英文逗号和分号
            parts = re.split(r'[;,，]', gene_text)
            gene_count = len([p for p in parts if p.strip()])

        # 计算预计文件总数
        expected_files = 0
        if ptype in ["cell", "both"]:
            expected_files += 1
        if ptype in ["gene", "both"]:
            expected_files += gene_count

        # 阈值判断 (>2 自动关闭，<=2 自动开启)
        should_check = (expected_files <= 2)

        # 只有状态不一样时才去设置，避免不必要的刷新
        if self.open_pdf_check.isChecked() != should_check:
            self.open_pdf_check.setChecked(should_check)
            # 可选：在日志或状态栏给点反馈 (太频繁就算了)
            print(f"[GUI] Auto-switch PDF option: {should_check} (Files: {expected_files})")

    def _pick_best_ref_col(self, cols):
        if not cols: return None
        target = "celltype"
        for i, c in enumerate(cols):
            if c.lower() == target: return i
        for i, c in enumerate(cols):
            if target in c.lower(): return i
        match = difflib.get_close_matches(target, cols, n=1, cutoff=0.4)
        if match: return cols.index(match[0])
        return 0

    def load_ref_cols(self, path):
        try:
            print(f"[GUI] Inspecting {Path(path).name} for columns...")
            QApplication.processEvents()

            ref = st.io.read_h5ad(path)
            # 获取 obs DataFrame
            if hasattr(ref, 'adata') and ref.adata is not None:
                obs = ref.adata.obs
            else:
                obs = ref.obs

            cols = list(obs.columns.astype(str))

            self.ref_col_combo.clear()
            self.ref_col_combo.addItems(cols)

            # 【新增】打印列内容预览 (Show first n items)
            print("[GUI] Column Previews:")
            for col in cols:
                try:
                    # 获取前5个唯一值用于预览
                    values = obs[col].unique()
                    preview_items = [str(v) for v in values[:5]]
                    preview_str = ", ".join(preview_items)
                    if len(values) > 5:
                        preview_str += ", ..."
                    print(f"   - {col}: [{preview_str}]")
                except Exception:
                    pass  # 某些特殊列无法预览，跳过

            best_idx = self._pick_best_ref_col(cols)
            if best_idx is not None:
                self.ref_col_combo.setCurrentIndex(best_idx)
                print(f"[GUI] Auto-selected column: {cols[best_idx]}")

            print("[GUI] Columns loaded.")

        except Exception as e:
            msg = f"Error reading ref columns: {e}"
            print(f"[GUI] {msg}")
            QMessageBox.warning(self, "Load Error", f"Failed to inspect reference file:\n\n{e}")

    def update_output_filenames_for_region(self, new_region: str):
        prev_region = self._current_region
        if prev_region == new_region: return
        prev_defs = self.region_defaults.get(prev_region, {})
        new_defs = self.region_defaults.get(new_region, {})

        current_cell = self.out_cell_edit.text().strip()
        if current_cell:
            cell_path = Path(current_cell)
            if prev_defs.get("cell") and cell_path.name == prev_defs.get("cell"):
                new_name = new_defs.get("cell", cell_path.name)
                self.out_cell_edit.setText(str(cell_path.with_name(new_name)))

        current_gene = self.out_gene_edit.text().strip()
        if current_gene:
            gene_path = Path(current_gene)
            if prev_defs.get("gene") and gene_path.name == prev_defs.get("gene"):
                new_name = new_defs.get("gene", gene_path.name)
                self.out_gene_edit.setText(str(gene_path.with_name(new_name)))
        self._current_region = new_region

    def browse_ref(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Ref", "", "H5AD (*.h5ad)")
        if f:
            self.ref_edit.setText(f)
            self.load_ref_cols(f)

    def browse_main(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Data", "", "H5AD (*.h5ad)")
        if f: self.main_edit.setText(f)

    def browse_cell_output(self):
        self._browse_save(self.out_cell_edit, "cluster_scatter_output.pdf")

    def browse_gene_output(self):
        self._browse_save(self.out_gene_edit, "spatial_scatter_*.pdf")

    def _browse_save(self, line_edit, default_name):
        current = line_edit.text().strip() or default_name
        p = Path(current)
        initial = str(p.parent) if str(p.parent) != "." else ""
        name = p.name or default_name
        f, _ = QFileDialog.getSaveFileName(self, "Save Output", str(Path(initial) / name), "PDF (*.pdf)")
        if f:
            if not f.lower().endswith(".pdf"): f += ".pdf"
            line_edit.setText(f)

    def start_run(self):
        ref_path = self.ref_edit.text().strip()
        main_path = self.main_edit.text().strip()
        ref_col = self.ref_col_combo.currentText().strip()

        if not ref_path or not main_path or not ref_col:
            QMessageBox.warning(self, "Missing Input", "Please provide paths and reference column.")
            return

        region = "eye"
        for btn in self.region_group.buttons():
            if btn.isChecked(): region = btn.text()

        ptype = self.plot_group.checkedButton().property("plotType")
        genes = self.gene_edit.text().strip() or None

        if ptype != "cell" and not genes:
            QMessageBox.warning(self, "Missing Gene", "Plot type requires gene name(s).")
            return

        method = "rapids" if "Auto" in self.method_combo.currentText() else "cpu"

        # GC Logic
        if self.cached_main_path != main_path:
            if self.cached_main_data is not None:
                print(">>> Main path changed. Cleaning old memory...")
                self.cached_main_data = None
                gc.collect()
            self.cached_main_path = main_path

        if self.cached_ref_path != ref_path:
            if self.cached_ref_data is not None:
                self.cached_ref_data = None
                gc.collect()
            self.cached_ref_path = ref_path

        config = AnnotationConfig(
            ref_path=ref_path,
            ref_used_col=ref_col,
            data_region=region,
            main_data_path=main_path,
            out_pdf=self.out_cell_edit.text(),
            method=method,
            gene=genes,
            plot_type=ptype,
            gene_out_pattern=self.out_gene_edit.text(),
            preloaded_main_data=self.cached_main_data,
            preloaded_ref_data=self.cached_ref_data
        )

        self.set_interface_locked(True)
        self.btn_stack.setCurrentIndex(1)

        # 【修复】改用 print，避免 append() 产生的额外空行
        print("=" * 30)
        print("[GUI] Starting Annotation Run...")

        self.worker = Worker(config)
        self.worker.finished_signal.connect(self.on_run_finished)
        self.worker.error_signal.connect(self.on_run_error)
        self.worker.start()

    def on_run_finished(self, data, method, files):
        self.set_interface_locked(False)
        self.btn_stack.setCurrentIndex(0)

        print(f"[GUI] DONE! Method used: {method}")
        print("-" * 30)

        if self.open_pdf_check.isChecked():
            to_open = []
            to_open.extend(files.get('cell', []))
            to_open.extend(files.get('gene', []))
            for fpath in to_open:
                self.open_file(fpath)

    def on_run_error(self, err_msg):
        self.set_interface_locked(False)
        self.btn_stack.setCurrentIndex(0)
        QMessageBox.critical(self, "Error", f"An error occurred:\n{err_msg}")

        # 【修复】改用 print
        print(f"[GUI] [ERROR] {err_msg}")

    def open_file(self, filepath):
        try:
            if platform.system() == 'Darwin':
                subprocess.call(('open', filepath))
            elif platform.system() == 'Windows':
                os.startfile(filepath)
            else:
                subprocess.call(('xdg-open', filepath))
        except Exception:
            pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())