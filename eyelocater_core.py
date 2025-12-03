# eyelocater_core.py
"""
Core utilities for running SingleR-based annotation on Stereo data.
"""
from __future__ import annotations

import os

# 【关键修改】必须在导入 stereo 或 pyplot 之前设置 Agg 后端
# 这能防止 Matplotlib 试图在子线程创建 GUI 窗口，从而避免 QObject 线程错误
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

import warnings
import copy
import sys
from dataclasses import dataclass
from typing import Optional, Literal, Dict, List, Tuple

import stereo as st

Region = Literal["eye", "retina", "cornea"]

# Mapping of cluster IDs
CLUSTER_TO_LOCATION: Dict[str, str] = {
    "1": "lens", "2": "lens", "3": "lens", "4": "lens", "5": "unknown",
    "6": "retina", "7": "lens", "8": "sclera & choroid", "9": "lens",
    "10": "retina", "11": "retina", "12": "iris & ciliary",
    "13": "sclera & choroid", "14": "iris & ciliary", "15": "retina",
    "16": "retina", "17": "cornea", "18": "cornea", "19": "cornea",
    "20": "retina", "21": "cornea", "22": "retina",
    "23": "sclera & choroid", "24": "sclera & choroid", "25": "retina",
    "26": "iris & ciliary", "27": "lens", "28": "retina", "29": "retina",
    "30": "unknown", "31": "optic nerve", "32": "retina", "33": "retina",
    "34": "unknown", "35": "lens", "36": "iris & ciliary", "37": "iris & ciliary",
    "38": "iris & ciliary", "39": "unknown", "40": "unknown", "41": "unknown",
    "42": "sclera & choroid", "43": "retina", "44": "unknown", "45": "unknown",
    "46": "unknown", "47": "unknown", "48": "unknown", "49": "unknown",
    "50": "unknown",
}


class AnnotationError(Exception):
    pass


@dataclass
class AnnotationConfig:
    ref_path: str
    ref_used_col: str
    data_region: Region
    main_data_path: str = "data/DR_only_stereo.h5ad"
    out_pdf: str = "cluster_scatter_output.pdf"
    method: str = "rapids"
    suppress_warnings: bool = True
    gene: Optional[str] = None
    plot_type: Literal["cell", "gene", "both"] = "cell"
    gene_out_pattern: str = "spatial_scatter_*.pdf"
    preloaded_main_data: Optional[object] = None
    preloaded_ref_data: Optional[object] = None


def load_main_data(path: str):
    print(f"[Core] Loading main data from: {path} ...")
    try:
        data = st.io.read_stereo_h5ad(path)
        return data
    except Exception as e:
        raise AnnotationError(f"Error loading main data file '{path}': {e}") from e


def load_and_preprocess_ref(path: str):
    print(f"[Core] Loading reference from: {path} ...")
    try:
        ref = st.io.read_h5ad(path)
    except Exception as e:
        raise AnnotationError(f"Error loading reference file '{path}': {e}") from e

    try:
        # 【修复】兼容 AnnBasedStereoExpData (无直接 .uns 属性)
        already_logged = False

        # 1. 检查内部 AnnData
        if hasattr(ref, 'adata') and ref.adata is not None:
            if hasattr(ref.adata, 'uns') and ref.adata.uns is not None:
                if 'log1p' in ref.adata.uns:
                    already_logged = True
        # 2. 检查对象本身 (兼容旧版)
        elif hasattr(ref, 'uns') and ref.uns is not None:
            if 'log1p' in ref.uns:
                already_logged = True

        if not already_logged:
            print("[Core] Preprocessing reference (normalize + log1p)...")
            ref.tl.normalize_total()
            ref.tl.log1p()
        else:
            print("[Core] Reference seems already processed (log1p found). Skipping.")

    except Exception as e:
        # 即使检查出错也不要崩溃，打印警告并继续
        print(f"[Core WARN] Could not check log1p status: {e}. Assuming not processed.")
        try:
            ref.tl.normalize_total()
            ref.tl.log1p()
        except Exception as e2:
            raise AnnotationError(f"Error during reference preprocessing: {e2}") from e2
    return ref


def _run_singler(data, ref, ref_used_col: str, prefer_method: str = "rapids") -> str:
    import traceback
    def _call(method: str) -> str:
        print(f"[Core] Running single_r with method={method!r}...")
        data.tl.single_r(
            ref_exp_data=ref,
            ref_use_col=ref_used_col,
            res_key="annotation",
            method=method,
        )
        return method

    try:
        return _call(prefer_method)
    except Exception as e:
        msg = str(e)
        if "don't have GPU related RAPIDS packages" in msg and prefer_method.lower() == "rapids":
            print("[Core] RAPIDS not available; falling back to CPU.")
            try:
                return _call("cpu")
            except Exception as e2:
                traceback.print_exc()
                raise AnnotationError(f"single_r failed with fallback CPU: {e2}") from e2
        else:
            traceback.print_exc()
            raise AnnotationError(f"Error during annotation ({prefer_method}): {msg}") from e


def _filter_by_region(data, region: Region):
    if region == "eye":
        return

    print(f"[Core] Filtering data for region: {region}")
    if region not in ("retina", "cornea"):
        raise AnnotationError(f"Invalid region '{region}'")

    if "phenograph" not in data.tl.result:
        raise AnnotationError("Could not find 'phenograph' results in data.tl.result.")

    try:
        res = data.tl.result["phenograph"].copy()
        res["location"] = res["group"].map(CLUSTER_TO_LOCATION)
        bins = res.loc[res["location"] == region, "bins"].tolist()
        data.tl.filter_cells(cell_list=bins)
    except Exception as e:
        raise AnnotationError(f"Error during filtering for region '{region}': {e}") from e


def _plot_and_save(data, config: AnnotationConfig) -> Dict[str, List[str]]:
    plot_files: Dict[str, List[str]] = {"cell": [], "gene": []}

    # 强制清理，防止内存残留
    plt.close('all')

    try:
        # --- Cell Plot ---
        if config.plot_type in ("cell", "both"):
            print(f"[Core] Plotting clusters to {config.out_pdf}...")
            # 显式创建 figure，不依赖全局状态
            data.plt.cluster_scatter(res_key="annotation", dot_size=2)
            fig = plt.gcf()
            ax = plt.gca()
            fig.set_size_inches(8, 7)
            ax.set_aspect("equal", adjustable="box")

            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)

            fig.tight_layout()
            plt.savefig(config.out_pdf, format="pdf", bbox_inches='tight')
            plot_files["cell"].append(config.out_pdf)

            abs_path = os.path.abspath(config.out_pdf)
            print(f"[Core] Cell plot saved to: {abs_path}")

            plt.close(fig)  # 立即关闭

        # --- Gene Plot ---
        if config.plot_type in ("gene", "both"):
            genes = _parse_gene_list(config.gene)
            if genes:
                valid_genes = [g for g in genes if g in data.gene_names]
                if not valid_genes:
                    print(f"[Core][WARN] No valid genes found in: {genes}")

                for g in valid_genes:
                    print(f"[Core] Plotting gene {g}...")
                    data.plt.spatial_scatter_by_gene(g)

                    pattern = config.gene_out_pattern or "spatial_scatter_*.pdf"
                    if "*" in pattern:
                        out_name = pattern.replace("*", g)
                    else:
                        base = pattern.rsplit(".", 1)[0]
                        out_name = f"{base}_{g}.pdf"

                    plt.savefig(out_name, format="pdf", bbox_inches='tight')
                    plot_files["gene"].append(out_name)

                    abs_path = os.path.abspath(out_name)
                    print(f"[Core] Gene plot ({g}) saved to: {abs_path}")  # <--- 加在这里

                    plt.close(plt.gcf())

    except Exception as e:
        raise AnnotationError(f"Plotting error: {e}") from e

    return plot_files


def _parse_gene_list(gene_str: Optional[str]) -> List[str]:
    if not gene_str: return []
    import re
    parts = re.split(r"[;,]", gene_str)
    return [p.strip() for p in parts if p.strip()]


def run_annotation_with_info(config: AnnotationConfig):
    if config.suppress_warnings:
        warnings.filterwarnings("ignore")

    # 1. 准备主数据
    if config.preloaded_main_data is not None:
        print("[Core] Using cached Main Data (Creating a working copy)...")
        try:
            data = copy.deepcopy(config.preloaded_main_data)
        except Exception:
            print("[Core] Deepcopy failed, reloading from disk to be safe.")
            data = load_main_data(config.main_data_path)
    else:
        data = load_main_data(config.main_data_path)

    # 2. 准备参考数据
    if config.preloaded_ref_data is not None:
        print("[Core] Using cached Reference Data.")
        ref = config.preloaded_ref_data
    else:
        ref = load_and_preprocess_ref(config.ref_path)

    # 3. 运行分析
    method_used = _run_singler(data, ref, config.ref_used_col, config.method)

    # 4. 过滤
    _filter_by_region(data, config.data_region)

    # 5. 绘图
    plot_files = _plot_and_save(data, config)

    return data, method_used, plot_files