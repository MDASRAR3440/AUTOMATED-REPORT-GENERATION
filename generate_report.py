#!/usr/bin/env python3
"""
generate_report.py

Single-file automated report generator:
- reads CSV input
- computes summary statistics
- groups by a categorical column
- creates plots (time series + bar)
- writes a PDF with a cover, summary table, and embedded charts

Usage:
    python generate_report.py --input sample_data.csv --output sample_report.pdf \
        --date-col date --group-col category --value-col value

Author: Generated for MDASRAR3440 repository
"""
import argparse
import io
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import pagesizes, units
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Image,
)
from reportlab.lib import colors

# -----------------------
# Data processing helpers
# -----------------------
def read_data(path: Path, date_col: str = None):
    """Read CSV into DataFrame, optionally parse date column."""
    df = pd.read_csv(path)
    if date_col and date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def summary_stats(df: pd.DataFrame, value_col: str):
    """Return a dict of basic statistics for the numeric column."""
    ser = pd.to_numeric(df[value_col], errors="coerce").dropna()
    stats = {
        "count": int(ser.count()),
        "mean": float(ser.mean()) if not ser.empty else None,
        "std": float(ser.std()) if not ser.empty else None,
        "min": float(ser.min()) if not ser.empty else None,
        "25%": float(ser.quantile(0.25)) if not ser.empty else None,
        "50% (median)": float(ser.median()) if not ser.empty else None,
        "75%": float(ser.quantile(0.75)) if not ser.empty else None,
        "max": float(ser.max()) if not ser.empty else None,
    }
    return stats


def group_summary(df: pd.DataFrame, group_col: str, value_col: str, top_n=10):
    """Return aggregated summary by group_col."""
    if group_col not in df.columns:
        return pd.DataFrame()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    grouped = df.groupby(group_col)[value_col].agg(["count", "mean", "sum"]).reset_index()
    grouped = grouped.sort_values("sum", ascending=False).head(top_n)
    return grouped


def timeseries_aggregate(df: pd.DataFrame, date_col: str, value_col: str, freq="D"):
    """Aggregate numeric values over time (resample by freq)."""
    if date_col not in df.columns:
        return pd.DataFrame()
    ts = df.set_index(pd.to_datetime(df[date_col], errors="coerce"))
    ts[value_col] = pd.to_numeric(ts[value_col], errors="coerce")
    agg = ts[value_col].resample(freq).sum().fillna(0)
    return agg


# -----------------------
# Figure creation
# -----------------------
def plot_timeseries(series: pd.Series, out_path: Path, title: str = "Time series"):
    """Plot time series and save to out_path (PNG)."""
    plt.figure(figsize=(10, 4))
    if series.index.dtype == "datetime64[ns]":
        plt.plot(series.index, series.values, marker="o", linewidth=1)
        plt.gcf().autofmt_xdate()
    else:
        plt.plot(series.values, marker="o", linewidth=1)
    plt.title(title)
    plt.xlabel("Date")
    plt.ylabel("Value")
    plt.grid(True, linestyle="--", linewidth=0.5, alpha=0.7)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_bar(df_grouped: pd.DataFrame, out_path: Path, label_col: str = None, value_col: str = "sum", title="By category"):
    """Plot a bar chart for grouped data frame with label_col and value_col."""
    plt.figure(figsize=(8, 4))
    if df_grouped.empty:
        # blank placeholder figure
        plt.text(0.5, 0.5, "No data", ha="center", va="center")
    else:
        labels = df_grouped[label_col].astype(str).tolist()
        values = df_grouped[value_col].tolist()
        plt.bar(range(len(labels)), values)
        plt.xticks(range(len(labels)), labels, rotation=45, ha="right")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


# -----------------------
# PDF generation
# -----------------------
def build_pdf(output_path: Path, context: dict):
    """
    Create a PDF report using reportlab's SimpleDocTemplate + platypus.
    context keys:
      - title, subtitle, generated_on (str)
      - source_info (str)
      - stats (dict)
      - grouped_df (pd.DataFrame)
      - timeseries_plot (Path)
      - bar_plot (Path)
    """
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    # Title page
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=24, alignment=1, spaceAfter=12)
    story.append(Paragraph(context.get("title", "Automated Report"), title_style))
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=12, alignment=1, spaceAfter=6)
    story.append(Paragraph(context.get("subtitle", ""), subtitle_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Generated on: {context.get('generated_on')}", styles["Normal"]))
    story.append(Paragraph(f"Source: {context.get('source_info', '')}", styles["Normal"]))
    story.append(Spacer(1, 18))

    # Summary statistics table
    story.append(Paragraph("Summary statistics", styles["Heading2"]))
    stats = context.get("stats", {})
    if stats:
        stat_rows = [["Metric", "Value"]]
        for k, v in stats.items():
            stat_rows.append([str(k), f"{v:.2f}" if isinstance(v, (int, float)) else str(v)])
        tbl = Table(stat_rows, hAlign="LEFT", colWidths=[150, 150])
        tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                 ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                 ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story.append(tbl)
    else:
        story.append(Paragraph("No numeric summary available.", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Grouped summary table
    story.append(Paragraph("Group summary (top groups)", styles["Heading2"]))
    gdf = context.get("grouped_df")
    if gdf is not None and not gdf.empty:
        # limit number of columns and rows for PDF
        cols = gdf.columns.tolist()
        data = [cols] + gdf.head(20).values.tolist()
        tbl = Table(data, hAlign="LEFT")
        tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                 ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
        story.append(tbl)
    else:
        story.append(Paragraph("No grouping data available.", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Add figures if exist
    for fig_label in ("timeseries_plot", "bar_plot"):
        fpath = context.get(fig_label)
        if fpath and Path(fpath).exists():
            story.append(Paragraph(fig_label.replace("_", " ").title(), styles["Heading3"]))
            # Insert image with max width set to page width minus margins
            img = Image(str(fpath))
            max_width = A4[0] - doc.leftMargin - doc.rightMargin
            if img.drawWidth > max_width:
                img.drawWidth = max_width
                img.drawHeight = img.drawHeight * (max_width / img.drawWidth)
            story.append(img)
            story.append(Spacer(1, 12))

    doc.build(story)


# -----------------------
# CLI / main
# -----------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Automated Report Generator")
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output PDF file path")
    parser.add_argument("--date-col", default="date", help="Date column name (optional)")
    parser.add_argument("--group-col", default="category", help="Group / category column name")
    parser.add_argument("--value-col", default="value", help="Numeric value column name")
    parser.add_argument("--freq", default="D", help="Timeseries resample frequency (D, W, M)")
    parser.add_argument("--top-n", type=int, default=10, help="Number of top groups to show")
    args = parser.parse_args(argv)

    inp = Path(args.input)
    out = Path(args.output)
    workdir = out.parent
    workdir.mkdir(parents=True, exist_ok=True)

    # Read
    print(f"Reading {inp} ...")
    df = read_data(inp, date_col=args.date_col)

    # Stats
    print("Calculating summary statistics ...")
    stats = summary_stats(df, args.value_col)

    # Grouping
    print(f"Computing group summary by '{args.group_col}' ...")
    grouped = group_summary(df, args.group_col, args.value_col, top_n=args.top_n)

    # Timeseries
    print(f"Aggregating timeseries by '{args.date_col}' freq='{args.freq}' ...")
    ts = timeseries_aggregate(df, args.date_col, args.value_col, freq=args.freq)

    # Create plots
    timeseries_png = workdir / "timeseries.png"
    bar_png = workdir / "bar.png"

    if not ts.empty:
        print(f"Plotting timeseries -> {timeseries_png}")
        plot_timeseries(ts, timeseries_png, title=f"Timeseries ({args.value_col})")
    else:
        # Create empty placeholder
        print("No timeseries data; creating placeholder timeseries figure.")
        plt.figure(figsize=(8, 3))
        plt.text(0.5, 0.5, "No time series data", ha="center", va="center")
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(timeseries_png)
        plt.close()

    print(f"Plotting bar chart -> {bar_png}")
    plot_bar(grouped, bar_png, label_col=args.group_col, value_col="sum", title="Top groups by sum")

    # Build PDF
    context = {
        "title": "Automated Data Report",
        "subtitle": f"Source: {inp.name}",
        "generated_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_info": str(inp),
        "stats": stats,
        "grouped_df": grouped,
        "timeseries_plot": str(timeseries_png),
        "bar_plot": str(bar_png),
    }
    print(f"Building PDF -> {out} ...")
    build_pdf(out, context)
    print("Done.")


if __name__ == "__main__":
    main()
