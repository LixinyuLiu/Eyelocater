#!/usr/bin/env python
import argparse
import warnings
import stereo as st

def main():
    # Suppress warnings
    warnings.filterwarnings('ignore')
    
    # Set up command-line arguments
    parser = argparse.ArgumentParser(
        description="Annotate main data using a reference h5ad file with GPU-accelerated singleR method, optionally filter cells, and save a cluster scatter plot as PDF."
    )
    parser.add_argument(
        '-ref',
        required=True,
        type=str,
        help='Path to the reference h5ad file.'
    )
    parser.add_argument(
        '-ref_used_col',
        required=True,
        type=str,
        help='Column in the reference file to be used for annotation (e.g., ClusterName).'
    )
    parser.add_argument(
        '-data',
        required=True,
        type=str,
        choices=['eye', 'retina', 'cornea'],
        help="Specify the anatomical region: 'eye' (no filtering), 'retina', or 'cornea'."
    )
    args = parser.parse_args()

    # Load main data file (default location)
    main_data_path = 'output_data/DR_only_stereo.h5ad'
    try:
        data = st.io.read_stereo_h5ad(main_data_path)
        print(f"Loaded main data from '{main_data_path}'.")
    except Exception as e:
        print(f"Error loading main data file '{main_data_path}': {e}")
        return

    # Load reference file
    try:
        ref = st.io.read_h5ad(args.ref)
        print(f"Loaded reference data from '{args.ref}'.")
    except Exception as e:
        print(f"Error loading reference file '{args.ref}': {e}")
        return

    # Preprocess the reference data
    try:
        ref.tl.normalize_total()
        ref.tl.log1p()
        print("Reference data preprocessing completed.")
    except Exception as e:
        print(f"Error during reference data preprocessing: {e}")
        return

    # Perform GPU-accelerated annotation using the reference data
    try:
        data.tl.single_r(
            ref_exp_data=ref,
            ref_use_col=args.ref_used_col,
            res_key='annotation',
            method='rapids'  # Use GPU acceleration
        )
        print("Annotation completed successfully!")
    except Exception as e:
        print(f"Error during annotation: {e}")
        return

    # Optionally filter cells based on anatomical region
    if args.data == 'eye':
        print("Using 'eye' data; no additional filtering applied.")
    elif args.data in ['retina', 'cornea']:
        # Mapping of cluster IDs to anatomical locations
        cluster_to_location = {
            '1': 'lens',
            '2': 'lens',
            '3': 'lens',
            '4': 'lens',
            '5': 'unknown',  
            '6': 'retina',
            '7': 'lens',
            '8': 'sclera & choroid',
            '9': 'lens',
            '10': 'retina',
            '11': 'retina',
            '12': 'iris & ciliary',
            '13': 'sclera & choroid',
            '14': 'iris & ciliary',
            '15': 'retina',
            '16': 'retina',
            '17': 'cornea',
            '18': 'cornea',
            '19': 'cornea',
            '20': 'retina',
            '21': 'cornea',
            '22': 'retina',
            '23': 'sclera & choroid',
            '24': 'sclera & choroid',
            '25': 'retina',
            '26': 'iris & ciliary',
            '27': 'lens',
            '28': 'retina',
            '29': 'retina',
            '30': 'unknown',
            '31': 'optic nerve',
            '32': 'retina',
            '33': 'retina',
            '34': 'unknown',
            '35': 'lens',
            '36': 'iris & ciliary',
            '37': 'iris & ciliary',
            '38': 'iris & ciliary',
            '39': 'unknown',
            '40': 'unknown',
            '41': 'unknown',
            '42': 'sclera & choroid',
            '43': 'retina',
            '44': 'unknown',
            '45': 'unknown',
            '46': 'unknown',
            '47': 'unknown',
            '48': 'unknown',
            '49': 'unknown',
            '50': 'unknown'
        }
        try:
            # Assume the phenograph clustering result is stored as a pandas DataFrame in data.tl.result['phenograph']
            res = data.tl.result['phenograph']
            # Map cluster IDs (assumed to be in the 'group' column) to anatomical locations
            res['location'] = res['group'].map(cluster_to_location)
            # Filter cells based on the target region ('retina' or 'cornea')
            target_region = args.data
            bins = res.loc[res['location'] == target_region, 'bins'].tolist()
            data.tl.filter_cells(cell_list=bins)
            print(f"Cells filtered for region '{target_region}' successfully!")
        except Exception as e:
            print(f"Error during filtering for region '{args.data}': {e}")
            return
    else:
        print("Invalid option for -data. Choose from 'eye', 'retina', or 'cornea'.")
        return

    # Generate and save the cluster scatter plot as a PDF using the provided snippet
    try:
        # Generate the cluster scatter plot with dot size 2
        data.plt.cluster_scatter(res_key='annotation', dot_size=2)
        import matplotlib.pyplot as plt
        plt.savefig('cluster_scatter_output.pdf', format='pdf')
        plt.show()  # Optional: display the plot
        print("Cluster scatter plot saved as 'cluster_scatter_output.pdf'.")
    except Exception as e:
        print(f"Error generating or saving the cluster scatter plot: {e}")

if __name__ == '__main__':
    main()
