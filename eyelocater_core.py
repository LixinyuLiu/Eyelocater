# eyelocater_core.py
"""
Core utilities for running SingleR-based annotation on Stereo data.

This is a light refactor of EMA's original singleR_annotation.py:
- same logic and defaults
- but exposed as a reusable function for CLI / GUI / notebooks
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional, Literal, Dict
import argparse
import sys
import stereo as st
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import Optional, Literal, Dict, List, Tuple
import argparse
import sys
import re
from dataclasses import dataclass
from typing import Optional, Literal, Dict, List, Tuple

import stereo as st
import matplotlib.pyplot as plt


# region =============================== Core ===============================

Region = Literal["eye", "retina", "cornea"]





# Mapping of cluster IDs to anatomical locations (copied from EMA's script)
CLUSTER_TO_LOCATION: Dict[str, str] = {
    "1": "lens",
    "2": "lens",
    "3": "lens",
    "4": "lens",
    "5": "unknown",
    "6": "retina",
    "7": "lens",
    "8": "sclera & choroid",
    "9": "lens",
    "10": "retina",
    "11": "retina",
    "12": "iris & ciliary",
    "13": "sclera & choroid",
    "14": "iris & ciliary",
    "15": "retina",
    "16": "retina",
    "17": "cornea",
    "18": "cornea",
    "19": "cornea",
    "20": "retina",
    "21": "cornea",
    "22": "retina",
    "23": "sclera & choroid",
    "24": "sclera & choroid",
    "25": "retina",
    "26": "iris & ciliary",
    "27": "lens",
    "28": "retina",
    "29": "retina",
    "30": "unknown",
    "31": "optic nerve",
    "32": "retina",
    "33": "retina",
    "34": "unknown",
    "35": "lens",
    "36": "iris & ciliary",
    "37": "iris & ciliary",
    "38": "iris & ciliary",
    "39": "unknown",
    "40": "unknown",
    "41": "unknown",
    "42": "sclera & choroid",
    "43": "retina",
    "44": "unknown",
    "45": "unknown",
    "46": "unknown",
    "47": "unknown",
    "48": "unknown",
    "49": "unknown",
    "50": "unknown",
}


class AnnotationError(Exception):
    """Raised when something goes wrong in the annotation pipeline."""

@dataclass
class AnnotationConfig:
    ref_path: str
    ref_used_col: str
    data_region: Region
    main_data_path: str = "data/DR_only_stereo.h5ad"
    out_pdf: str = "cluster_scatter_output.pdf"
    method: str = "rapids"  # GPU mode from EMA's script
    suppress_warnings: bool = True
    show_plot: bool = True  # match EMA: plt.show()
    gene: Optional[str] = None
    plot_type: Literal["cell", "gene", "both"] = "cell",
    gene_out_pattern: str = "spatial_scatter_*.pdf"



def _load_main_data(path: str):
    try:
        data = st.io.read_stereo_h5ad(path)
    except Exception as e:
        raise AnnotationError(f"Error loading main data file '{path}': {e}") from e
    return data


def _load_and_preprocess_ref(path: str):
    try:
        ref = st.io.read_h5ad(path)
    except Exception as e:
        raise AnnotationError(f"Error loading reference file '{path}': {e}") from e

    try:
        ref.tl.normalize_total()
        ref.tl.log1p()
    except Exception as e:
        raise AnnotationError(f"Error during reference data preprocessing: {e}") from e

    return ref


def _run_singler(data, ref, ref_used_col: str, prefer_method: str = "rapids") -> str:
    """
    prefer_method: "rapids" 或 "cpu"
    实际流程：尽量用 prefer_method，rapids 不可用时自动退回 cpu。

    Returns
    -------
    method_used : str
        "rapids" 或 "cpu"
    """
    import traceback

    def _call(method: str) -> str:
        print(f"[Eyelocater] Trying single_r with method={method!r}")
        data.tl.single_r(
            ref_exp_data=ref,
            ref_use_col=ref_used_col,
            res_key="annotation",
            method=method,
        )
        print(f"[Eyelocater] single_r finished with method={method!r}")
        return method

    tried: List[str] = []
    method = prefer_method

    try:
        tried.append(method)
        return _call(method)
    except Exception as e:
        msg = str(e)
        # 针对 stereo 的这句错误做特判：
        # "Your env don't have GPU related RAPIDS packages"
        if "don't have GPU related RAPIDS packages" in msg and method.lower() == "rapids":
            print("[Eyelocater] RAPIDS not available; falling back to method='cpu'.")
            try:
                tried.append("cpu")
                return _call("cpu")
            except Exception:
                traceback.print_exc()
                raise AnnotationError(
                    "single_r failed with both 'rapids' and 'cpu'. "
                    f"Methods tried: {tried}"
                ) from e
        else:
            traceback.print_exc()
            raise AnnotationError(
                f"Error during annotation with method={method}. Message: {msg}"
            ) from e





def _filter_by_region(data, region: Region):
    if region == "eye":
        # no additional filtering
        return

    if region not in ("retina", "cornea"):
        raise AnnotationError(
            f"Invalid region '{region}'. "
            "Expected one of: 'eye', 'retina', 'cornea'."
        )

    try:
        res = data.tl.result["phenograph"]  # EMA's assumption
    except Exception as e:
        raise AnnotationError(
            "Could not find 'phenograph' results in data.tl.result. "
            "Make sure phenograph clustering has been run."
        ) from e

    try:
        res["location"] = res["group"].map(CLUSTER_TO_LOCATION)
        bins = res.loc[res["location"] == region, "bins"].tolist()
        data.tl.filter_cells(cell_list=bins)
    except Exception as e:
        raise AnnotationError(
            f"Error during filtering for region '{region}': {e}"
        ) from e


def _parse_gene_list(gene_str: Optional[str]) -> List[str]:
    """把逗号/分号分隔的基因字符串解析成去重后的 list。"""
    if not gene_str:
        return []
    import re as _re
    parts = _re.split(r"[;,]", gene_str)
    cleaned: List[str] = []
    seen = set()
    for p in parts:
        g = p.strip()
        if not g:
            continue
        if g in seen:
            continue
        seen.add(g)
        cleaned.append(g)
    return cleaned


def _validate_genes(data, genes: List[str]) -> Tuple[List[str], List[str]]:
    """根据 StereoExpData.gene_names 返回 (valid_genes, invalid_genes)。"""
    if not genes:
        return [], []

    try:
        available = set(map(str, data.gene_names))
    except Exception as e:
        raise AnnotationError(f"Could not access gene names from data: {e}") from e

    valid = [g for g in genes if g in available]
    invalid = [g for g in genes if g not in available]

    if invalid:
        print(f"[Eyelocater][WARN] The following genes were not found in this dataset: {invalid}")

    return valid, invalid



def _plot_and_save(data, config: AnnotationConfig) -> Dict[str, List[str]]:
    """
    根据 config.plot_type 决定画哪些图，返回：
        {
          "cell": [...cell-level pdf...],
          "gene": [...gene-level pdf...],
        }
    """
    plot_files: Dict[str, List[str]] = {"cell": [], "gene": []}

    try:
        # 1) cell-level：按 annotation 上色
        if config.plot_type in ("cell", "both"):
            print("[Eyelocater] Generating cluster_scatter by annotation...")
            data.plt.cluster_scatter(res_key="annotation", dot_size=2)
            plt.savefig(config.out_pdf, format="pdf")
            print(f"Cluster scatter plot saved as '{config.out_pdf}'.")
            plot_files["cell"].append(config.out_pdf)
            if config.show_plot:
                plt.show()
            plt.close()

        # 2) gene-level：按 gene 表达上色（支持多个 gene）
        if config.plot_type in ("gene", "both"):
            genes = _parse_gene_list(config.gene)
            if not genes:
                print(
                    "[Eyelocater][WARN] plot_type is 'gene' or 'both' but no gene was "
                    "provided; skipping gene plots."
                )
            else:
                valid_genes, invalid_genes = _validate_genes(data, genes)
                if not valid_genes:
                    raise AnnotationError(
                        f"No valid genes found among requested: {genes!r}. "
                        f"Invalid genes: {invalid_genes!r}"
                    )

                pattern = config.gene_out_pattern or "spatial_scatter_*.pdf"

                for g in valid_genes:
                    print(f"[Eyelocater] Generating spatial_scatter_by_gene for {g!r}...")
                    data.plt.spatial_scatter_by_gene(g)

                    if "*" in pattern:
                        out_gene_pdf = pattern.replace("*", g)
                    else:
                        # 没有 * 的话就把 gene 塞到文件名里
                        if "." in pattern:
                            base, ext = pattern.rsplit(".", 1)
                            out_gene_pdf = f"{base}_{g}.{ext}"
                        else:
                            out_gene_pdf = f"{pattern}_{g}.pdf"

                    plt.savefig(out_gene_pdf, format="pdf")
                    print(f"Spatial scatter plot by gene saved as '{out_gene_pdf}'.")
                    plot_files["gene"].append(out_gene_pdf)
                    if config.show_plot:
                        plt.show()
                    plt.close()

    except Exception as e:
        raise AnnotationError(
            f"Error generating or saving plots: {e}"
        ) from e
    finally:
        plt.close("all")

    return plot_files



def run_annotation_with_info(config: AnnotationConfig):
    """
    完整 pipeline，返回 data + 实际使用的 method + 输出的图文件列表。
    """
    if config.suppress_warnings:
        warnings.filterwarnings("ignore")

    data = _load_main_data(config.main_data_path)
    ref = _load_and_preprocess_ref(config.ref_path)

    method_used = _run_singler(data, ref, config.ref_used_col, config.method)
    _filter_by_region(data, config.data_region)
    plot_files = _plot_and_save(data, config)

    return data, method_used, plot_files


def run_annotation(config: AnnotationConfig):
    """
    Overload version for compatibility.
    """
    data, _, _ = run_annotation_with_info(config)
    return data

# endregion


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Annotate Stereo main data using a reference h5ad file via SingleR. "
            "Optionally filter cells by anatomical region and save a cluster scatter plot as PDF."
        )
    )

    parser.add_argument(
        "-ref",
        required=True,
        type=str,
        help="Path to the reference h5ad file.",
    )
    parser.add_argument(
        "-ref_used_col",
        required=True,
        type=str,
        help="Column in the reference file to be used for annotation (e.g., ClusterName).",
    )
    parser.add_argument(
        "-data",
        required=True,
        choices=["eye", "retina", "cornea"],
        help="Anatomical region: 'eye' (no filtering), 'retina', or 'cornea'.",
    )

    # 新增几个可选参数，保持默认行为不变
    parser.add_argument(
        "--main_data",
        default="data/DR_only_stereo.h5ad",
        help="Path to the main Stereo h5ad file. "
             "Default: data/DR_only_stereo.h5ad",
    )
    parser.add_argument(
        "--out",
        default="cluster_scatter_output.pdf",
        help="Output PDF filename for the cluster scatter plot.",
    )
    parser.add_argument(
        "--method",
        default="rapids",
        choices=["rapids", "cpu"],
        help="SingleR backend method. Default: rapids (GPU).",
    )
    parser.add_argument(
        "--gene",
        default=None,
        help=(
            "Gene name(s) for gene-level plots. "
            "Use comma- or semicolon-separated list, e.g. 'Rho,Opn1mw,Opn1sw'."
        ),
    )
    parser.add_argument(
        "--plot_type",
        default="cell",
        choices=["cell", "gene", "both"],
        help="What to plot: 'cell', 'gene', or 'both'. Default: cell.",
    )
    parser.add_argument(
        "--gene_out",
        default="spatial_scatter_*.pdf",
        help=(
            "Output filename pattern for gene plots. Use '*' as placeholder "
            "for gene name, e.g. 'spatial_scatter_*.pdf'."
        ),
    )

    parser.add_argument(
        "--no_show",
        action="store_true",
        help="Do not display the plot window; only save the PDF.",
    )
    parser.add_argument(
        "--no_suppress_warnings",
        action="store_true",
        help="Do not suppress Python warnings.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    config = AnnotationConfig(
        ref_path=args.ref,
        ref_used_col=args.ref_used_col,
        data_region=args.data,
        main_data_path=args.main_data,
        out_pdf=args.out,
        method=args.method,
        show_plot=not args.no_show,
        suppress_warnings=not args.no_suppress_warnings,
        gene=args.gene,
        plot_type=args.plot_type,
        gene_out_pattern=args.gene_out,
    )

    try:
        _, method_used, plot_files = run_annotation_with_info(config)
        msg_parts = [f"Annotation completed successfully. Method used: {method_used!r}."]
        if plot_files.get("cell"):
            msg_parts.append(f"Cell plots: {plot_files['cell']}")
        if plot_files.get("gene"):
            msg_parts.append(f"Gene plots: {plot_files['gene']}")
        print(" ".join(msg_parts))
    except AnnotationError as e:
        print(f"[AnnotationError] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[Unexpected error] {e}", file=sys.stderr)
        sys.exit(1)



if __name__ == "__main__":
    main()
