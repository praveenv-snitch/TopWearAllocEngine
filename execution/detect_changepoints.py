# execution/detect_changepoints.py
import os
import calendar
import numpy as np
import pandas as pd
import openpyxl
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.marker import Marker

# Set Matplotlib writeable config directory inside project workspace
os.environ['MPLCONFIGDIR'] = os.path.abspath('.tmp/matplotlib')
os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)

import matplotlib
matplotlib.use('Agg')  # Headless mode to avoid GUI/system font sandbox blocks
import matplotlib.pyplot as plt
import ruptures as rpt

# Define the Indian Festival Calendar (2023-2026)
FESTIVALS = [
    # 2023
    ("2023-01-01", "New Year's Day"),
    ("2023-01-26", "Republic Day"),
    ("2023-02-18", "Maha Shivratri"),
    ("2023-03-08", "Holi"),
    ("2023-04-22", "Eid-ul-Fitr"),
    ("2023-06-29", "Eid-ul-Adha (Bakrid)"),
    ("2023-08-15", "Independence Day"),
    ("2023-08-29", "Onam (Thiruvonam)"),
    ("2023-08-30", "Raksha Bandhan"),
    ("2023-09-07", "Krishna Janmashtami"),
    ("2023-09-19", "Ganesh Chaturthi"),
    ("2023-10-24", "Dussehra"),
    ("2023-11-12", "Diwali"),
    ("2023-12-25", "Christmas"),

    # 2024
    ("2024-01-01", "New Year's Day"),
    ("2024-01-26", "Republic Day"),
    ("2024-03-08", "Maha Shivratri"),
    ("2024-03-25", "Holi"),
    ("2024-04-10", "Eid-ul-Fitr"),
    ("2024-06-17", "Eid-ul-Adha (Bakrid)"),
    ("2024-08-15", "Independence Day"),
    ("2024-08-19", "Raksha Bandhan"),
    ("2024-08-26", "Krishna Janmashtami"),
    ("2024-09-07", "Ganesh Chaturthi"),
    ("2024-09-15", "Onam (Thiruvonam)"),
    ("2024-10-12", "Dussehra"),
    ("2024-10-31", "Diwali"),
    ("2024-12-25", "Christmas"),

    # 2025
    ("2025-01-01", "New Year's Day"),
    ("2025-01-26", "Republic Day"),
    ("2025-02-26", "Maha Shivratri"),
    ("2025-03-14", "Holi"),
    ("2025-03-31", "Eid-ul-Fitr"),
    ("2025-06-07", "Eid-ul-Adha (Bakrid)"),
    ("2025-08-09", "Raksha Bandhan"),
    ("2025-08-15", "Independence Day"),
    ("2025-08-16", "Krishna Janmashtami"),
    ("2025-08-27", "Ganesh Chaturthi"),
    ("2025-09-04", "Onam (Thiruvonam)"),
    ("2025-10-02", "Dussehra"),
    ("2025-10-20", "Diwali"),
    ("2025-12-25", "Christmas"),

    # 2026
    ("2026-01-01", "New Year's Day"),
    ("2026-01-14", "Makar Sankranti"),
    ("2026-01-26", "Republic Day"),
    ("2026-02-15", "Maha Shivratri"),
    ("2026-03-04", "Holi"),
    ("2026-03-20", "Eid-ul-Fitr"),
    ("2026-05-27", "Eid-ul-Adha (Bakrid)"),
    ("2026-08-15", "Independence Day"),
    ("2026-08-26", "Onam (Thiruvonam)"),
    ("2026-08-28", "Raksha Bandhan"),
    ("2026-09-04", "Krishna Janmashtami"),
    ("2026-09-14", "Ganesh Chaturthi"),
    ("2026-10-20", "Dussehra"),
    ("2026-11-08", "Diwali"),
    ("2026-12-25", "Christmas"),
]

festival_dates = [(pd.to_datetime(d), name) for d, name in FESTIVALS]

def get_period_start_date(dt):
    """Maps a datetime to its calendar-aligned 15-day period start date."""
    if dt.month == 2:
        if dt.day <= 14:
            return pd.Timestamp(year=dt.year, month=dt.month, day=1)
        else:
            return pd.Timestamp(year=dt.year, month=dt.month, day=15)
    else:
        if dt.day <= 15:
            return pd.Timestamp(year=dt.year, month=dt.month, day=1)
        else:
            return pd.Timestamp(year=dt.year, month=dt.month, day=16)

def get_period_label(dt):
    """Formats a period start date to a human-readable text label, aligning Feb 2nd half."""
    year = dt.year
    month_name = calendar.month_name[dt.month]
    if dt.month == 2:
        if dt.day == 1:
            return f"1 Feb - 14 Feb {year}"
        else:
            # Force "15 Feb - 28 Feb" for consistency across leap and non-leap years
            return f"15 Feb - 28 Feb {year}"
    else:
        if dt.day == 1:
            return f"1 {month_name[:3]} - 15 {month_name[:3]} {year}"
        else:
            _, last_day = calendar.monthrange(year, dt.month)
            return f"16 {month_name[:3]} - {last_day} {month_name[:3]} {year}"

def get_year_group_and_period_name(dt):
    """Aligns dates to standard July-June fiscal year overlay bins (Force 15-28 Feb)."""
    year = dt.year
    month = dt.month
    day = dt.day
    
    if month >= 7:
        year_group = f"{year}-{year+1}"
    else:
        year_group = f"{year-1}-{year}"
        
    month_offset = (month - 7) % 12
    if month == 2:
        period_idx = month_offset * 2 + (1 if day <= 14 else 2)
    else:
        period_idx = month_offset * 2 + (1 if day <= 15 else 2)
        
    month_name = calendar.month_name[month][:3]
    if month == 2:
        if day == 1:
            p_name = "1-14 Feb"
        else:
            p_name = "15-28 Feb"  # Force same label for all years to avoid line breaks
    else:
        if day == 1:
            p_name = f"1-15 {month_name}"
        else:
            _, last_day = calendar.monthrange(year, month)
            p_name = f"16-{last_day} {month_name}"
            
    return year_group, period_idx, p_name

def get_weather_season(dt):
    """Classifies the date into a typical Indian weather season."""
    month = dt.month
    if month in [3, 4, 5]:
        return "Summer (Mar-May)"
    elif month in [6, 7, 8, 9]:
        return "Monsoon (Jun-Sep)"
    elif month in [10, 11]:
        return "Autumn/Festive (Oct-Nov)"
    else:
        return "Winter (Dec-Feb)"

def get_retail_sales_season(dt):
    """Classifies the date into typical retail promotion/sales cycle in India."""
    month = dt.month
    day = dt.day
    if (month == 6 and day >= 15) or month == 7:
        return "Summer EOSS (Jun-Jul)"
    elif month in [1, 2]:
        return "Winter EOSS (Jan-Feb)"
    elif month in [9, 10]:
        return "Pre-Festive / Festive Promo (Sep-Oct)"
    else:
        return "Baseline / Regular Retail"

def find_nearest_festival(target_date):
    """Finds the nearest festival within 14 days of target_date."""
    nearest_fest = ""
    min_diff = 999
    
    for f_date, f_name in festival_dates:
        diff_days = (f_date - target_date).days
        abs_diff = abs(diff_days)
        if abs_diff <= 14 and abs_diff < min_diff:
            min_diff = abs_diff
            sign = "+" if diff_days >= 0 else "-"
            nearest_fest = f"{f_name} ({sign}{abs_diff} days)"
            
    return nearest_fest

def main():
    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Read raw data
    units_file = "data/raw/daily_units.csv"
    stores_file = "data/raw/daily_active_stores.csv"
    sales_history_file = "data/raw/sales_history.csv"
    
    if not os.path.exists(units_file) or not os.path.exists(stores_file):
        print(f"Error: Raw files not found at {units_file} or {stores_file}.")
        print("Please run the Snowflake pull script first.")
        return

    df_units = pd.read_csv(units_file)
    df_stores = pd.read_csv(stores_file)
    
    # Standardize column casing to lowercase
    df_units.columns = [c.lower() for c in df_units.columns]
    df_stores.columns = [c.lower() for c in df_stores.columns]
    
    df_units['sale_date'] = pd.to_datetime(df_units['sale_date'])
    df_stores['sale_date'] = pd.to_datetime(df_stores['sale_date'])
    
    # Step 2: Merge and normalize daily
    df_merged = pd.merge(df_units, df_stores, on='sale_date', how='inner')
    df_merged = df_merged[df_merged['active_stores'] > 0]
    df_merged['demand_per_store'] = df_merged['total_units'] / df_merged['active_stores']
    df_merged.to_csv("data/processed/normalized_daily_demand.csv", index=False)
    
    # Step 3: Compute unique stores using sales_history.csv
    print("Calculating unique store counts per period from sales history...")
    if os.path.exists(sales_history_file):
        df_sales = pd.read_csv(sales_history_file)
        df_sales.columns = [c.lower() for c in df_sales.columns]
        df_sales['sale_date'] = pd.to_datetime(df_sales['order_date'])
        df_sales['period_start'] = df_sales['sale_date'].apply(get_period_start_date)
        df_unique_stores = df_sales.groupby('period_start')['branch_code'].nunique().reset_index()
        df_unique_stores.rename(columns={'branch_code': 'unique_store_count'}, inplace=True)
    else:
        print("Warning: sales_history.csv not found, using maximum active store daily count.")
        df_merged['period_start'] = df_merged['sale_date'].apply(get_period_start_date)
        df_unique_stores = df_merged.groupby('period_start')['active_stores'].max().reset_index()
        df_unique_stores.rename(columns={'active_stores': 'unique_store_count'}, inplace=True)
        
    # Custom calendar-aligned aggregation
    df_merged['period_start'] = df_merged['sale_date'].apply(get_period_start_date)
    df_period = df_merged.groupby('period_start').agg(
        total_demand=('total_units', 'sum'),
        smoothed_demand=('demand_per_store', 'mean')
    ).reset_index()
    
    # Merge unique stores
    df_period = pd.merge(df_period, df_unique_stores, on='period_start', how='left')
    df_period['unique_store_count'] = df_period['unique_store_count'].fillna(1).astype(int)
    df_period.rename(columns={'unique_store_count': 'no_of_stores'}, inplace=True)
    
    df_period = df_period.sort_values('period_start').reset_index(drop=True)
    df_period['period_label'] = df_period['period_start'].apply(get_period_label)
    
    # Save smoothed demand table
    cols = ['period_start', 'period_label', 'total_demand', 'no_of_stores', 'smoothed_demand']
    df_period = df_period[cols]
    df_period.to_csv("data/processed/smoothed_demand.csv", index=False)
    print("Saved aggregated data to data/processed/smoothed_demand.csv (with Unique Store Counts)")
    
    # Step 4: Write native Excel charts
    print("Generating logs/demand_analysis_charts.xlsx with native Excel charts...")
    yg, p_idx, p_name = [], [], []
    for dt in df_period['period_start']:
        y_val, idx_val, name_val = get_year_group_and_period_name(dt)
        yg.append(y_val)
        p_idx.append(idx_val)
        p_name.append(name_val)
        
    df_period_chart = df_period.copy()
    df_period_chart['year_group'] = yg
    df_period_chart['period_idx'] = p_idx
    df_period_chart['period_name_no_year'] = p_name
    
    # Filter: Keep ONLY the three full requested years
    valid_years = ['2023-2024', '2024-2025', '2025-2026']
    df_period_chart = df_period_chart[df_period_chart['year_group'].isin(valid_years)]
    
    # Pivoting tables
    df_pivot = df_period_chart.pivot(index=['period_idx', 'period_name_no_year'], columns='year_group', values='smoothed_demand').reset_index()
    df_pivot = df_pivot.sort_values('period_idx').reset_index(drop=True)
    
    df_pivot_demand = df_period_chart.pivot(index=['period_idx', 'period_name_no_year'], columns='year_group', values='total_demand').reset_index()
    df_pivot_demand = df_pivot_demand.sort_values('period_idx').reset_index(drop=True)
    
    df_pivot_stores = df_period_chart.pivot(index=['period_idx', 'period_name_no_year'], columns='year_group', values='no_of_stores').reset_index()
    df_pivot_stores = df_pivot_stores.sort_values('period_idx').reset_index(drop=True)
    
    wb = openpyxl.Workbook()
    
    # Tab 1: Smoothed Demand Overlay
    ws1 = wb.active
    ws1.title = "Smoothed Demand Overlay"
    
    year_cols = ['2023-2024', '2024-2025', '2025-2026']
    ws1.append(["Period Label"] + year_cols)
    for _, r in df_pivot.iterrows():
        row_vals = [r['period_name_no_year']]
        for col in year_cols:
            val = r[col] if col in r else None
            row_vals.append(None if pd.isna(val) else float(val))
        ws1.append(row_vals)
        
    # Chart 1: Line Chart
    c1 = LineChart()
    c1.title = "Year-over-Year Smoothed Demand Comparison"
    c1.y_axis.title = "Smoothed Demand (Units/Store/Day)"
    c1.x_axis.title = "Period of the Year"
    c1.width = 30  # Larger canvas size (30 cm) so labels fit
    c1.height = 15  # Height 15 cm
    
    c1.x_axis.visible = True
    c1.y_axis.visible = True
    c1.x_axis.type = "cat"  # Explicitly force Category Axis (text labels)
    c1.x_axis.lblRotation = 4500  # Rotate labels by 45 degrees
    c1.y_axis.majorGridlines = openpyxl.chart.axis.ChartLines()
    
    data1 = Reference(ws1, min_col=2, min_row=1, max_col=1 + len(year_cols), max_row=1 + len(df_pivot))
    cats1 = Reference(ws1, min_col=1, min_row=2, max_row=1 + len(df_pivot))
    c1.add_data(data1, titles_from_data=True)
    c1.set_categories(cats1)
    
    # Format line styles: Colors (Navy Blue, Emerald Green, Coral Red) + Markers
    colors = ["1F497D", "385723", "C00000"]
    for i, s in enumerate(c1.series):
        color = colors[i % len(colors)]
        s.marker = Marker()
        s.marker.symbol = "circle"
        s.marker.size = 5
        s.marker.graphicalProperties.solidFill = color
        s.marker.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.width = 25000  # 2.5pt
        
    ws1.add_chart(c1, "F2")
    
    # Tab 2: Total Demand Overlay
    ws2 = wb.create_sheet(title="Total Demand Overlay")
    ws2.append(["Period Label (Stores)"] + year_cols)
    
    for i in range(len(df_pivot_demand)):
        p_name = df_pivot_demand.loc[i, 'period_name_no_year']
        
        # Get store count for each year
        s1 = int(df_pivot_stores.loc[i, '2023-2024']) if '2023-2024' in df_pivot_stores.columns and not pd.isna(df_pivot_stores.loc[i, '2023-2024']) else 0
        s2 = int(df_pivot_stores.loc[i, '2024-2025']) if '2024-2025' in df_pivot_stores.columns and not pd.isna(df_pivot_stores.loc[i, '2024-2025']) else 0
        s3 = int(df_pivot_stores.loc[i, '2025-2026']) if '2025-2026' in df_pivot_stores.columns and not pd.isna(df_pivot_stores.loc[i, '2025-2026']) else 0
        
        lbl_with_stores = f"{p_name} ({s1}|{s2}|{s3} stores)"
        
        row_vals = [lbl_with_stores]
        for col in year_cols:
            val = df_pivot_demand.loc[i, col] if col in df_pivot_demand.columns else None
            row_vals.append(None if pd.isna(val) else float(val))
        ws2.append(row_vals)
        
    # Chart 2: Line chart of total demand
    c2 = LineChart()
    c2.title = "Year-over-Year Total Demand Comparison"
    c2.y_axis.title = "Total Demand (Units)"
    c2.x_axis.title = "Period of the Year (Store Counts Yr 1|2|3)"
    c2.width = 30
    c2.height = 15
    
    c2.x_axis.visible = True
    c2.y_axis.visible = True
    c2.x_axis.type = "cat"
    c2.x_axis.lblRotation = 4500
    c2.y_axis.majorGridlines = openpyxl.chart.axis.ChartLines()
    
    data2 = Reference(ws2, min_col=2, min_row=1, max_col=1 + len(year_cols), max_row=1 + len(df_pivot_demand))
    cats2 = Reference(ws2, min_col=1, min_row=2, max_row=1 + len(df_pivot_demand))
    c2.add_data(data2, titles_from_data=True)
    c2.set_categories(cats2)
    
    # Format line styles for total demand chart
    for i, s in enumerate(c2.series):
        color = colors[i % len(colors)]
        s.marker = Marker()
        s.marker.symbol = "circle"
        s.marker.size = 5
        s.marker.graphicalProperties.solidFill = color
        s.marker.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.width = 25000
        
    ws2.add_chart(c2, "F2")
    
    wb.save("logs/demand_analysis_charts.xlsx")
    print("Successfully generated logs/demand_analysis_charts.xlsx")
    
    # --- Generate static PNG plots using Matplotlib ---
    print("Generating logs/smoothed_demand_overlay_plot.png...")
    plt.figure(figsize=(16, 8))
    categories = df_pivot['period_name_no_year'].values
    hex_colors = ["#1F497D", "#385723", "#C00000"]
    years_labels = ["July 23 - June 24", "July 24 - June 25", "July 25 - June 26"]
    
    for i, col in enumerate(year_cols):
        # We fill NaNs with a line plot that connects gaps cleanly, but for visual comparison:
        y_vals = df_pivot[col].values
        # Matplotlib handles NaN by breaking the line, so we can interpolate or show it
        # Let's plot with markers on valid data points
        plt.plot(range(len(categories)), y_vals, marker='o', markersize=6, linewidth=2, color=hex_colors[i], label=years_labels[i])
        
    plt.title("Year-over-Year Smoothed Demand Comparison (T-Shirts Category)", fontsize=14, fontweight='bold', pad=15)
    plt.ylabel("Smoothed Demand (Units/Store/Day)", fontsize=12)
    plt.xlabel("Period of the Year", fontsize=12)
    plt.xticks(ticks=range(len(categories)), labels=categories, rotation=45, ha='right', fontsize=10)
    plt.yticks(fontsize=10)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig("logs/smoothed_demand_overlay_plot.png", dpi=150)
    plt.close()
    
    print("Generating logs/total_demand_overlay_plot.png...")
    plt.figure(figsize=(18, 8))
    
    lbls_with_stores = []
    for i in range(len(df_pivot_demand)):
        p_name = df_pivot_demand.loc[i, 'period_name_no_year']
        s1 = int(df_pivot_stores.loc[i, '2023-2024']) if '2023-2024' in df_pivot_stores.columns and not pd.isna(df_pivot_stores.loc[i, '2023-2024']) else 0
        s2 = int(df_pivot_stores.loc[i, '2024-2025']) if '2024-2025' in df_pivot_stores.columns and not pd.isna(df_pivot_stores.loc[i, '2024-2025']) else 0
        s3 = int(df_pivot_stores.loc[i, '2025-2026']) if '2025-2026' in df_pivot_stores.columns and not pd.isna(df_pivot_stores.loc[i, '2025-2026']) else 0
        lbls_with_stores.append(f"{p_name}\n({s1}|{s2}|{s3} stores)")
        
    for i, col in enumerate(year_cols):
        y_vals = df_pivot_demand[col].values
        plt.plot(range(len(lbls_with_stores)), y_vals, marker='o', markersize=6, linewidth=2, color=hex_colors[i], label=years_labels[i])
        
    plt.title("Year-over-Year Total Demand Comparison with Active Store Counts", fontsize=14, fontweight='bold', pad=15)
    plt.ylabel("Total Demand (Units)", fontsize=12)
    plt.xlabel("Period of the Year\n(Active Store Count for: July 23 - June 24 | July 24 - June 25 | July 25 - June 26)", fontsize=12)
    plt.xticks(ticks=range(len(lbls_with_stores)), labels=lbls_with_stores, rotation=45, ha='right', fontsize=9)
    plt.yticks(fontsize=10)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig("logs/total_demand_overlay_plot.png", dpi=150)
    plt.close()
    
    # Step 5: Changepoint Detection for pen = 1, 2, 5
    signal = df_period['smoothed_demand'].values
    penalties = [1, 2, 5]
    
    print("\n--- Running PELT Changepoint Detection Sensitivity ---")
    for pen in penalties:
        algo = rpt.Pelt(model="rbf").fit(signal)
        changepoints = algo.predict(pen=pen)
        cp_indices = changepoints[:-1]
        
        print(f"Penalty = {pen:2d}: Found {len(cp_indices)} changepoint(s) at indices: {cp_indices}")
        
        # Build changepoints table
        cp_rows = []
        boundaries = [0] + cp_indices + [len(signal)]
        
        for i in range(len(boundaries) - 2):
            prev_bound = boundaries[i]
            curr_cp = boundaries[i+1]
            next_bound = boundaries[i+2]
            
            cp_date = df_period.iloc[curr_cp]['period_start']
            cp_label = df_period.iloc[curr_cp]['period_label']
            
            # Demand before: mean of signal in segment [prev_bound, curr_cp)
            demand_before = np.mean(signal[prev_bound:curr_cp])
            # Demand after: mean of signal in segment [curr_cp, next_bound)
            demand_after = np.mean(signal[curr_cp:next_bound])
            
            pct_change = ((demand_after - demand_before) / demand_before) * 100 if demand_before > 0 else 0.0
            festival_info = find_nearest_festival(cp_date)
            weather_season = get_weather_season(cp_date)
            retail_sale = get_retail_sales_season(cp_date)
            
            cp_rows.append({
                'changepoint_date': cp_date.strftime('%Y-%m-%d'),
                'period_label': cp_label,
                'demand_level_before': round(demand_before, 4),
                'demand_level_after': round(demand_after, 4),
                'percent_change': round(pct_change, 2),
                'typical_weather_season': weather_season,
                'retail_sales_season': retail_sale,
                'nearest_known_festival_within_14_days': festival_info
            })
            
        cp_df = pd.DataFrame(cp_rows)
        out_csv = f"logs/detected_changepoints_pen{pen}.csv"
        cp_df.to_csv(out_csv, index=False)
        
        print(f"Saved changepoints table for pen={pen} to {out_csv}")
        if not cp_df.empty:
            print(cp_df.to_string(index=False))
        else:
            print("[No changepoints detected]")
        print("-" * 60)

if __name__ == "__main__":
    main()
