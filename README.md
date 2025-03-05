# Eyelocater
Identifying single cell localisation based on a mouse eye atlas.

## Overview
Eyelocater is a tool designed for the spatial analysis of single-cell datasets using a comprehensive mouse eye atlas. It enables users to determine cell localisation within the eye, aiding in the understanding of cellular organization and function.

## Features
Single-Cell Localisation: Easily integrate your own single-cell datasets.\
GUI-Based Analysis: An interactive graphical interface simplifies data exploration.\
High-Throughput: Designed to work with h5ad formatted data for efficient processing.\

## Prerequisites
```bash
conda env create -f st_environment.yml
conda activate eyelocater_env  # Replace with the environment name if different
```
## Download Data
Download your data and place it in the data folder inside the Eyelocater directory. \
The data is: xxxx

## Usage
```bash
python3 GUI.py
```
reference h5ad file: your single-cell data \
reference column: The column you have for cell-type \
Anatomical Region: choose between the Eye, retina, and cornea



