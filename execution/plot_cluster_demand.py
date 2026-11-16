# execution/plot_cluster_demand.py
import os
import json
import calendar
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Set Matplotlib writeable config directory inside project workspace
os.environ['MPLCONFIGDIR'] = os.path.abspath('.tmp/matplotlib')
os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)

import matplotlib
matplotlib.use('Agg')  # Headless mode to avoid GUI/system font sandbox blocks
import matplotlib.pyplot as plt

# Approved cluster-to-zone mapping
CLUSTER_TO_ZONE = {
    'AP': 'SOUTH',
    'BANGALORE': 'SOUTH',
    'HYDERABAD': 'SOUTH',
    'KARNATAKA': 'SOUTH',
    'KERALA': 'SOUTH',
    'MANGALORE': 'SOUTH',
    'TAMIL NADU': 'SOUTH',
    'DELHI': 'NORTH',
    'HARYANA': 'NORTH',
    'PUNJAB': 'NORTH',
    'RAJASTHAN': 'WEST',
    'UTTAR PRADESH': 'NORTH',
    'UTTARAKHAND': 'NORTH',
    'GUJARAT': 'WEST',
    'MAHARASHTRA': 'WEST',
    'MP': 'WEST',
    'ASSAM': 'EAST',
    'BIHAR': 'EAST',
    'CHHATTISGARH': 'EAST',
    'ODISHA': 'EAST'
}

# 20 distinct premium hex colors
DISTINCT_COLORS = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD", 
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#1A365D", "#2F855A", "#C53030", "#7B341E", "#9B2C2C",
    "#2B6CB0", "#4A5568", "#2D3748", "#B7791F", "#6B46C1"
]

def get_period_start_date(dt):
    """Maps a datetime to its calendar-aligned 15-day period start date (Jan 1st basis)."""
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

def get_calendar_period_info(dt):
    """Aligns dates to standard Jan-Dec calendar year periods (1 to 24) with short labels."""
    year = dt.year
    month = dt.month
    day = dt.day
    
    month_offset = month - 1
    if month == 2:
        period_idx = month_offset * 2 + (1 if day <= 14 else 2)
    else:
        period_idx = month_offset * 2 + (1 if day <= 15 else 2)
        
    month_name = calendar.month_name[month][:3]
    if month == 2:
        if day == 1:
            p_name = "1-14 Feb"
        else:
            p_name = "15-28 Feb"  # Force 15-28 Feb for all years
    else:
        if day == 1:
            p_name = f"1-15 {month_name}"
        else:
            _, last_day = calendar.monthrange(year, month)
            p_name = f"16-{last_day} {month_name}"
            
    return period_idx, p_name

def get_july_june_period_info(dt):
    """Aligns dates to standard July-June fiscal year periods (1 to 24) with short labels."""
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
            p_name = "15-28 Feb"
    else:
        if day == 1:
            p_name = f"1-15 {month_name}"
        else:
            _, last_day = calendar.monthrange(year, month)
            p_name = f"16-{last_day} {month_name}"
            
    return year_group, period_idx, p_name

def get_july_june_ref_date(dt):
    """Maps a date to a pseudo-date in 2025-2026 for July-June alignment (handles Feb 29)."""
    month = dt.month
    day = dt.day
    if month == 2 and day == 29:
        day = 28
    if month >= 7:
        return f"2025-{month:02d}-{day:02d}"
    else:
        return f"2026-{month:02d}-{day:02d}"

def main():
    os.makedirs("logs", exist_ok=True)
    demand_file = "data/raw/cluster_daily_demand.csv"
    
    if not os.path.exists(demand_file):
        print(f"Error: Raw file not found at {demand_file}.")
        print("Please run python execution/pull_cluster_data.py first.")
        return
        
    df_demand = pd.read_csv(demand_file)
    df_demand.columns = [c.lower() for c in df_demand.columns]
    df_demand['sale_date'] = pd.to_datetime(df_demand['sale_date'])
    df_demand['year'] = df_demand['sale_date'].dt.year
    
    # Exclude days with zero active stores
    df_demand = df_demand[df_demand['active_stores'] > 0]
    df_demand['demand_per_store'] = df_demand['total_units'] / df_demand['active_stores']
    
    # Map clusters to zones
    df_demand['cluster_name'] = df_demand['cluster_name'].str.upper().str.strip()
    df_demand['zone_name'] = df_demand['cluster_name'].map(CLUSTER_TO_ZONE)
    df_demand = df_demand[df_demand['zone_name'].notna()]
    
    zones = ['NORTH', 'SOUTH', 'EAST', 'WEST']
    years = [2024, 2025, 2026]
    
    # ----------------------------------------------------
    # 1. Structure Daily Zone Data (Tab 1)
    # ----------------------------------------------------
    plotly_daily_data = {yr: {zn: [] for zn in zones} for yr in years}
    for yr in years:
        df_yr = df_demand[df_demand['year'] == yr]
        if df_yr.empty:
            continue
        all_dates = pd.date_range(start=f"{yr}-01-01", end=f"{yr}-12-31")
        
        for zn in zones:
            df_yr_zn = df_yr[df_yr['zone_name'] == zn]
            if df_yr_zn.empty:
                continue
            clusters = df_yr_zn['cluster_name'].dropna().unique()
            for c_idx, cl in enumerate(clusters):
                df_c = df_yr_zn[df_yr_zn['cluster_name'] == cl]
                store_count = int(df_c['active_stores'].max())
                
                df_c_daily = df_c.set_index('sale_date').reindex(all_dates)
                df_c_daily['demand_per_store'] = df_c_daily['demand_per_store'].interpolate(limit_direction='both')
                y_vals = [None if pd.isna(y) or np.isinf(y) else float(y) for y in df_c_daily['demand_per_store'].values]
                
                plotly_daily_data[yr][zn].append({
                    "cluster": cl,
                    "store_count": store_count,
                    "x": [dt.strftime('%Y-%m-%d') for dt in all_dates],
                    "y": y_vals,
                    "color": DISTINCT_COLORS[c_idx % len(DISTINCT_COLORS)]
                })

    # ----------------------------------------------------
    # 2. Structure 15-Day Zone Average Data (Tab 2)
    # ----------------------------------------------------
    plotly_15day_data = {yr: {zn: [] for zn in zones} for yr in years}
    # Pre-generate standard calendar period labels for reference
    periods_ref = []
    for m in range(1, 13):
        for half in [1, 2]:
            dt_temp = pd.Timestamp(year=2025, month=m, day=1 if half == 1 else 16)
            _, lbl = get_calendar_period_info(dt_temp)
            periods_ref.append(lbl)
            
    df_demand['period_start'] = df_demand['sale_date'].apply(get_period_start_date)
    p_idx, p_label = [], []
    for dt in df_demand['period_start']:
        idx, lbl = get_calendar_period_info(dt)
        p_idx.append(idx)
        p_label.append(lbl)
    df_demand['period_idx'] = p_idx
    df_demand['period_name'] = p_label
    
    df_agg = df_demand.groupby(['cluster_name', 'zone_name', 'year', 'period_idx', 'period_name']).agg(
        smoothed_demand=('demand_per_store', 'mean'),
        max_stores=('active_stores', 'max')
    ).reset_index()
    
    for yr in years:
        df_yr = df_agg[df_agg['year'] == yr]
        if df_yr.empty:
            continue
        for zn in zones:
            df_yr_zn = df_yr[df_yr['zone_name'] == zn]
            if df_yr_zn.empty:
                continue
            clusters = df_yr_zn['cluster_name'].dropna().unique()
            for c_idx, cl in enumerate(clusters):
                df_c = df_yr_zn[df_yr_zn['cluster_name'] == cl]
                store_count = int(df_c['max_stores'].max())
                
                df_c_piv = df_c.set_index('period_name').reindex(periods_ref)
                y_vals = [None if pd.isna(y) or np.isinf(y) else float(y) for y in df_c_piv['smoothed_demand'].values]
                
                plotly_15day_data[yr][zn].append({
                    "cluster": cl,
                    "store_count": store_count,
                    "x": periods_ref,
                    "y": y_vals,
                    "color": DISTINCT_COLORS[c_idx % len(DISTINCT_COLORS)]
                })

    # ----------------------------------------------------
    # 3. Structure Company-wide Overlaid Data (Tab 3)
    # ----------------------------------------------------
    # Group daily data across all clusters to get company-wide totals
    df_company_daily = df_demand.groupby('sale_date').agg(
        total_units=('total_units', 'sum'),
        active_stores=('active_stores', 'sum')
    ).reset_index()
    df_company_daily['smoothed_demand'] = df_company_daily['total_units'] / df_company_daily['active_stores']
    
    yg_list, ref_dates_list = [], []
    for dt in df_company_daily['sale_date']:
        yg, _, _ = get_july_june_period_info(dt)
        yg_list.append(yg)
        ref_dates_list.append(get_july_june_ref_date(dt))
    df_company_daily['year_group'] = yg_list
    df_company_daily['ref_date'] = ref_dates_list
    
    # Filter to three specific overlay year groups
    valid_year_groups = ['2023-2024', '2024-2025', '2025-2026']
    df_company_daily = df_company_daily[df_company_daily['year_group'].isin(valid_year_groups)]
    
    company_plotly_daily = []
    # Base layout for reference date range
    ref_dates_ref = pd.date_range(start="2025-07-01", end="2026-06-30")
    ref_dates_ref_str = [dt.strftime('%Y-%m-%d') for dt in ref_dates_ref]
    
    year_group_labels = {
        "2023-2024": "July 23 - June 24",
        "2024-2025": "July 24 - June 25",
        "2025-2026": "July 25 - June 26"
    }
    company_colors = ["#1F497D", "#385723", "#C00000"]
    
    for i, yg in enumerate(valid_year_groups):
        df_yg = df_company_daily[df_company_daily['year_group'] == yg]
        if df_yg.empty:
            continue
        # Group by ref_date to aggregate duplicates (like Feb 29 and Feb 28 in leap years)
        df_yg = df_yg.groupby('ref_date')['smoothed_demand'].mean().reset_index()
        # Set index to ref_date, reindex to cover all 365 days of the July-June period
        df_yg_daily = df_yg.set_index('ref_date').reindex(ref_dates_ref_str)
        df_yg_daily['smoothed_demand'] = df_yg_daily['smoothed_demand'].interpolate(limit_direction='both')
        y_vals = [None if pd.isna(y) or np.isinf(y) else float(y) for y in df_yg_daily['smoothed_demand'].values]
        
        company_plotly_daily.append({
            "year_group": year_group_labels[yg],
            "x": ref_dates_ref_str,
            "y": y_vals,
            "color": company_colors[i]
        })
        
    # Company-wide 15-day period overlay (July - June)
    # Generate labels for reference (July to June)
    july_june_ref_periods = []
    for offset in range(12):
        m = (6 + offset) % 12 + 1
        month_name = calendar.month_name[m][:3]
        if m == 2:
            july_june_ref_periods.append("1-14 Feb")
            july_june_ref_periods.append("15-28 Feb")
        else:
            july_june_ref_periods.append(f"1-15 {month_name}")
            _, last_day = calendar.monthrange(2025, m)
            july_june_ref_periods.append(f"16-{last_day} {month_name}")
            
    df_company_daily['period_start'] = df_company_daily['sale_date'].apply(get_period_start_date)
    p_yg, p_idx_jj, p_lbl_jj = [], [], []
    for dt in df_company_daily['period_start']:
        yg, idx, lbl = get_july_june_period_info(dt)
        p_yg.append(yg)
        p_idx_jj.append(idx)
        p_lbl_jj.append(lbl)
    df_company_daily['year_group'] = p_yg
    df_company_daily['period_idx'] = p_idx_jj
    df_company_daily['period_name'] = p_lbl_jj
    
    df_company_agg = df_company_daily.groupby(['year_group', 'period_idx', 'period_name']).agg(
        smoothed_demand=('smoothed_demand', 'mean')
    ).reset_index()
    
    company_plotly_15day = []
    for i, yg in enumerate(valid_year_groups):
        df_yg = df_company_agg[df_company_agg['year_group'] == yg]
        if df_yg.empty:
            continue
        df_yg_piv = df_yg.set_index('period_name').reindex(july_june_ref_periods)
        y_vals = [None if pd.isna(y) or np.isinf(y) else float(y) for y in df_yg_piv['smoothed_demand'].values]
        
        company_plotly_15day.append({
            "year_group": year_group_labels[yg],
            "x": july_june_ref_periods,
            "y": y_vals,
            "color": company_colors[i]
        })

    # ----------------------------------------------------
    # 4. Generate Combined HTML Dashboard
    # ----------------------------------------------------
    print("\nGenerating logs/cluster_demand_interactive.html...")
    
    html_template = """<!DOCTYPE html>
<html>
<head>
    <title>Snitch Demand Interactive Dashboard</title>
    <!-- Load Plotly.js from CDN -->
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #f8fafc; color: #1e293b; }
        header { background-color: #0f172a; color: white; padding: 20px 40px; border-bottom: 4px solid #2563eb; }
        h1 { margin: 0 0 5px 0; font-weight: 800; font-size: 26px; }
        p.subtitle { color: #94a3b8; font-size: 13px; margin: 0; }
        
        .main-tabs { display: flex; background: #1e293b; padding: 0 40px; }
        .main-tab-btn { padding: 15px 25px; font-size: 15px; font-weight: bold; background: none; border: none; border-bottom: 3px solid transparent; color: #94a3b8; cursor: pointer; transition: all 0.2s ease; }
        .main-tab-btn:hover { color: white; }
        .main-tab-btn.active { color: white; border-bottom-color: #2563eb; }
        
        .content-area { padding: 30px 40px; }
        .section-panel { display: none; }
        .section-panel.active { display: block; }
        
        .sub-tabs { display: flex; margin-bottom: 20px; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }
        .sub-tab-btn { padding: 10px 25px; margin-right: 10px; font-size: 14px; font-weight: bold; background-color: #e2e8f0; border: none; border-radius: 5px; cursor: pointer; color: #475569; transition: all 0.2s ease; }
        .sub-tab-btn.active { background-color: #2563eb; color: white; }
        
        .zones-grid { display: grid; grid-template-columns: 1fr; gap: 30px; }
        @media(min-width: 1024px) {
            .zones-grid { grid-template-columns: repeat(2, 1fr); }
        }
        .company-grid { display: grid; grid-template-columns: 1fr; gap: 30px; }
        
        .chart-card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }
        .chart-title { font-size: 16px; font-weight: bold; color: #1e293b; margin-bottom: 15px; border-left: 4px solid #2563eb; padding-left: 10px; }
    </style>
</head>
<body>
    <header>
        <h1>Snitch T-Shirt Demand Analysis</h1>
        <p class="subtitle">Multi-dimensional unstacked dashboard comparing daily curves, 15-day window averages, and company-wide overlays.</p>
    </header>
    
    <div class="main-tabs">
        <button class="main-tab-btn active" onclick="showMainTab('daily-curves')">Daily Zone Curves (2D Curves)</button>
        <button class="main-tab-btn" onclick="showMainTab('15day-averages')">15-Day Zone Averages</button>
        <button class="main-tab-btn" onclick="showMainTab('company-wide')">Company-Wide Analysis</button>
    </div>
    
    <div class="content-area">
        <!-- Tab 1: Daily Zone Curves -->
        <div id="panel-daily-curves" class="section-panel active">
            <div class="sub-tabs">
                <button class="sub-tab-btn active" id="btn-daily-2024" onclick="showDailyYear('2024')">2024</button>
                <button class="sub-tab-btn" id="btn-daily-2025" onclick="showDailyYear('2025')">2025</button>
                <button class="sub-tab-btn" id="btn-daily-2026" onclick="showDailyYear('2026')">2026</button>
            </div>
            
            <div id="daily-panel-2024" class="daily-year-panel" style="display:block;">
                <div class="zones-grid">
                    <div class="chart-card"><div class="chart-title">North Zone</div><div id="chart-daily-2024-NORTH"></div></div>
                    <div class="chart-card"><div class="chart-title">South Zone</div><div id="chart-daily-2024-SOUTH"></div></div>
                    <div class="chart-card"><div class="chart-title">East Zone</div><div id="chart-daily-2024-EAST"></div></div>
                    <div class="chart-card"><div class="chart-title">West Zone</div><div id="chart-daily-2024-WEST"></div></div>
                </div>
            </div>
            <div id="daily-panel-2025" class="daily-year-panel" style="display:none;">
                <div class="zones-grid">
                    <div class="chart-card"><div class="chart-title">North Zone</div><div id="chart-daily-2025-NORTH"></div></div>
                    <div class="chart-card"><div class="chart-title">South Zone</div><div id="chart-daily-2025-SOUTH"></div></div>
                    <div class="chart-card"><div class="chart-title">East Zone</div><div id="chart-daily-2025-EAST"></div></div>
                    <div class="chart-card"><div class="chart-title">West Zone</div><div id="chart-daily-2025-WEST"></div></div>
                </div>
            </div>
            <div id="daily-panel-2026" class="daily-year-panel" style="display:none;">
                <div class="zones-grid">
                    <div class="chart-card"><div class="chart-title">North Zone</div><div id="chart-daily-2026-NORTH"></div></div>
                    <div class="chart-card"><div class="chart-title">South Zone</div><div id="chart-daily-2026-SOUTH"></div></div>
                    <div class="chart-card"><div class="chart-title">East Zone</div><div id="chart-daily-2026-EAST"></div></div>
                    <div class="chart-card"><div class="chart-title">West Zone</div><div id="chart-daily-2026-WEST"></div></div>
                </div>
            </div>
        </div>
        
        <!-- Tab 2: 15-Day Zone Averages -->
        <div id="panel-15day-averages" class="section-panel">
            <div class="sub-tabs">
                <button class="sub-tab-btn active" id="btn-15day-2024" onclick="show15DayYear('2024')">2024</button>
                <button class="sub-tab-btn" id="btn-15day-2025" onclick="show15DayYear('2025')">2025</button>
                <button class="sub-tab-btn" id="btn-15day-2026" onclick="show15DayYear('2026')">2026</button>
            </div>
            
            <div id="avg-panel-2024" class="avg-year-panel" style="display:block;">
                <div class="zones-grid">
                    <div class="chart-card"><div class="chart-title">North Zone (15-Day Averages)</div><div id="chart-15day-2024-NORTH"></div></div>
                    <div class="chart-card"><div class="chart-title">South Zone (15-Day Averages)</div><div id="chart-15day-2024-SOUTH"></div></div>
                    <div class="chart-card"><div class="chart-title">East Zone (15-Day Averages)</div><div id="chart-15day-2024-EAST"></div></div>
                    <div class="chart-card"><div class="chart-title">West Zone (15-Day Averages)</div><div id="chart-15day-2024-WEST"></div></div>
                </div>
            </div>
            <div id="avg-panel-2025" class="avg-year-panel" style="display:none;">
                <div class="zones-grid">
                    <div class="chart-card"><div class="chart-title">North Zone (15-Day Averages)</div><div id="chart-15day-2025-NORTH"></div></div>
                    <div class="chart-card"><div class="chart-title">South Zone (15-Day Averages)</div><div id="chart-15day-2025-SOUTH"></div></div>
                    <div class="chart-card"><div class="chart-title">East Zone (15-Day Averages)</div><div id="chart-15day-2025-EAST"></div></div>
                    <div class="chart-card"><div class="chart-title">West Zone (15-Day Averages)</div><div id="chart-15day-2025-WEST"></div></div>
                </div>
            </div>
            <div id="avg-panel-2026" class="avg-year-panel" style="display:none;">
                <div class="zones-grid">
                    <div class="chart-card"><div class="chart-title">North Zone (15-Day Averages)</div><div id="chart-15day-2026-NORTH"></div></div>
                    <div class="chart-card"><div class="chart-title">South Zone (15-Day Averages)</div><div id="chart-15day-2026-SOUTH"></div></div>
                    <div class="chart-card"><div class="chart-title">East Zone (15-Day Averages)</div><div id="chart-15day-2026-EAST"></div></div>
                    <div class="chart-card"><div class="chart-title">West Zone (15-Day Averages)</div><div id="chart-15day-2026-WEST"></div></div>
                </div>
            </div>
        </div>
        
        <!-- Tab 3: Company-wide Analysis -->
        <div id="panel-company-wide" class="section-panel">
            <div class="company-grid">
                <div class="chart-card">
                    <div class="chart-title">Company-Wide Daily 2D Curve Overlay (July - June)</div>
                    <div id="chart-company-daily"></div>
                </div>
                <div class="chart-card">
                    <div class="chart-title">Company-Wide 15-Day Window Line Graph Overlay (July - June)</div>
                    <div id="chart-company-15day"></div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Data injected from Python
        const dailyData = __DAILY_ZONES_DATA__;
        const avg15DayData = __AVG15DAY_ZONES_DATA__;
        const companyDailyData = __COMPANY_DAILY_DATA__;
        const company15DayData = __COMPANY_15DAY_DATA__;
        
        // Navigation: Main Tabs
        function showMainTab(tabId) {
            document.querySelectorAll('.section-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.main-tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('panel-' + tabId).classList.add('active');
            event.target.classList.add('active');
            window.dispatchEvent(new Event('resize'));
        }
        
        // Navigation: Daily Year Buttons
        function showDailyYear(year) {
            document.querySelectorAll('.daily-year-panel').forEach(p => p.style.display = 'none');
            document.querySelectorAll('#panel-daily-curves .sub-tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('daily-panel-' + year).style.display = 'block';
            document.getElementById('btn-daily-' + year).classList.add('active');
            window.dispatchEvent(new Event('resize'));
        }
        
        // Navigation: 15-Day Year Buttons
        function show15DayYear(year) {
            document.querySelectorAll('.avg-year-panel').forEach(p => p.style.display = 'none');
            document.querySelectorAll('#panel-15day-averages .sub-tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('avg-panel-' + year).style.display = 'block';
            document.getElementById('btn-15day-' + year).classList.add('active');
            window.dispatchEvent(new Event('resize'));
        }
        
        // Dynamic layouts
        function getLayout(yaxisTitle, isCategory = false) {
            return {
                margin: { l: 60, r: 20, t: 20, b: 65 },
                xaxis: {
                    type: isCategory ? 'category' : 'date',
                    tickformat: isCategory ? undefined : '%d %b',
                    dtick: isCategory ? undefined : 'M1',
                    tickangle: -45,
                    gridcolor: '#f1f5f9'
                },
                yaxis: {
                    title: yaxisTitle,
                    gridcolor: '#f1f5f9'
                },
                hovermode: 'closest',
                plot_bgcolor: '#ffffff',
                paper_bgcolor: '#ffffff',
                showlegend: true,
                legend: { orientation: 'h', y: -0.22 }
            };
        }
        
        const years = ['2024', '2025', '2026'];
        const zones = ['NORTH', 'SOUTH', 'EAST', 'WEST'];
        
        // Render 1. Daily Zone Graphs
        years.forEach(yr => {
            zones.forEach(zn => {
                const elementId = `chart-daily-${yr}-${zn}`;
                const clList = dailyData[yr][zn];
                if (!clList || clList.length === 0) {
                    document.getElementById(elementId).innerHTML = "<p style='color:#94a3b8; text-align:center; padding: 40px 0;'>No data available</p>";
                    return;
                }
                const traces = clList.map(t => ({
                    x: t.x,
                    y: t.y,
                    mode: 'lines',
                    name: `${t.cluster} (${t.store_count} stores)`,
                    line: { color: t.color, width: 2 }
                }));
                Plotly.newPlot(elementId, traces, getLayout('Demand (Units/Store/Day)'), { responsive: true, displayModeBar: false });
            });
        });
        
        // Render 2. 15-Day Zone Averages
        years.forEach(yr => {
            zones.forEach(zn => {
                const elementId = `chart-15day-${yr}-${zn}`;
                const clList = avg15DayData[yr][zn];
                if (!clList || clList.length === 0) {
                    document.getElementById(elementId).innerHTML = "<p style='color:#94a3b8; text-align:center; padding: 40px 0;'>No data available</p>";
                    return;
                }
                const traces = clList.map(t => ({
                    x: t.x,
                    y: t.y,
                    mode: 'lines+markers',
                    name: `${t.cluster} (${t.store_count} stores)`,
                    line: { color: t.color, width: 2 },
                    marker: { size: 5 }
                }));
                Plotly.newPlot(elementId, traces, getLayout('Average Demand (Units/Store/Day)', true), { responsive: true, displayModeBar: false });
            });
        });
        
        // Render 3. Company-Wide Daily Overlay
        const companyDailyTraces = companyDailyData.map(t => ({
            x: t.x,
            y: t.y,
            mode: 'lines',
            name: t.year_group,
            line: { color: t.color, width: 2.5 }
        }));
        Plotly.newPlot('chart-company-daily', companyDailyTraces, getLayout('Smoothed Demand (Units/Store/Day)'), { responsive: true, displayModeBar: false });
        
        // Render 4. Company-Wide 15-Day Overlay
        const company15DayTraces = company15DayData.map(t => ({
            x: t.x,
            y: t.y,
            mode: 'lines+markers',
            name: t.year_group,
            line: { color: t.color, width: 2.5 },
            marker: { size: 6 }
        }));
        Plotly.newPlot('chart-company-15day', company15DayTraces, getLayout('Average Demand (Units/Store/Day)', true), { responsive: true, displayModeBar: false });
    </script>
</body>
</html>
"""
    
    # Inject the structured data
    final_html = html_template.replace("__DAILY_ZONES_DATA__", json.dumps(plotly_daily_data))
    final_html = final_html.replace("__AVG15DAY_ZONES_DATA__", json.dumps(plotly_15day_data))
    final_html = final_html.replace("__COMPANY_DAILY_DATA__", json.dumps(company_plotly_daily))
    final_html = final_html.replace("__COMPANY_15DAY_DATA__", json.dumps(company_plotly_15day))
    
    with open("logs/cluster_demand_interactive.html", "w") as f:
        f.write(final_html)
    print("Successfully generated fully integrated Snitch Demand Interactive Dashboard at logs/cluster_demand_interactive.html")

if __name__ == "__main__":
    main()
