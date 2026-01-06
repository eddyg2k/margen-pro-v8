import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import io
import zipfile

# =========================================================
# CONFIG & PAGE SETUP
# =========================================================
st.set_page_config(page_title="Margen Pro VIII | Liquidator Elite", layout="wide", page_icon="💎")

# =========================================================
# PREMIUM GLASSMORPHISM CSS
# =========================================================
st.markdown("""
<style>
/* Main Background & Fonts */
:root {
    --bg-color: #0e1117;
    --card-bg: #1e2530;
    --text-primary: #e6e6e6;
    --text-secondary: #a0aab4;
    --accent: #00d4ff;
    --accent-gradient: linear-gradient(135deg, #00d4ff 0%, #005bea 100%);
    --success: #00fa9a;
    --warning: #ffbf00;
    --danger: #ff4b4b;
}

.stApp {
    background-color: var(--bg-color);
}

h1, h2, h3, h4, h5, h6 {
    color: var(--text-primary);
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-weight: 600;
}

/* Metric Cards */
.metric-card {
    background: var(--card-bg);
    border: 1px solid rgba(255, 255, 255, 0.1);
    padding: 20px;
    border-radius: 15px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
    text-align: center;
    transition: transform 0.2s;
}
.metric-card:hover {
    transform: translateY(-5px);
    border-color: var(--accent);
}
.metric-value {
    font-size: 2rem;
    font-weight: bold;
    background: var(--accent-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.metric-label {
    color: var(--text-secondary);
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 5px;
}

/* KPI Badges */
.badge {
    padding: 5px 10px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 0.8rem;
}
.badge-success { background: rgba(0, 250, 154, 0.15); color: var(--success); border: 1px solid var(--success); }
.badge-danger { background: rgba(255, 75, 75, 0.15); color: var(--danger); border: 1px solid var(--danger); }

/* Custom DataFrame */
[data-testid="stDataFrame"] {
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

/* Sidebar Styling */
[data-testid="stSidebar"] {
    background-color: #161b22;
    border-right: 1px solid rgba(255, 255, 255, 0.05);
}

</style>
""", unsafe_allow_html=True)

# =========================================================
# CORE LOGIC
# =========================================================

def clean_currency(x):
    """Normalize a currency-like value into a numeric-friendly value.

    - Handles pandas/Numpy missing values (pd.NA, np.nan)
    - Decodes bytes
    - Strips common currency symbols and grouping commas
    - Handles negatives in parentheses (e.g. (1,234.56))
    - Returns a float when parseable, np.nan for empty/missing, or the cleaned string as a fallback
    """
    # Preserve pandas/Numpy NA
    try:
        if pd.isna(x):
            return np.nan
    except Exception:
        pass

    # Decode bytes if necessary
    if isinstance(x, (bytes, bytearray)):
        try:
            x = x.decode('utf-8')
        except Exception:
            x = x.decode('latin1', errors='ignore')

    # If it's a string, normalize
    if isinstance(x, str):
        s = x.strip()
        if s == '':
            return np.nan

        negative = False
        if s.startswith('(') and s.endswith(')'):
            negative = True
            s = s[1:-1].strip()

        # Remove common currency/grouping characters
        for ch in ['$', '€', '£', ',', '%', '\xa0']:
            s = s.replace(ch, '')

        # Normalize unicode minus
        s = s.replace('−', '-')
        s = s.strip()

        if s in ['', '--', '-']:
            return np.nan

        # Try to parse as float
        try:
            val = float(s)
            return -val if negative else val
        except Exception:
            # Leave as cleaned string; pd.to_numeric(..., errors='coerce') will handle it later
            return s

    # For numeric types, return unchanged
    return x


def load_data(uploaded_files):
    all_data = []
    
    for file in uploaded_files:
        try:
            if file.name.endswith('.csv'):
                try:
                    df = pd.read_csv(file, encoding='utf-8-sig')
                except:
                    file.seek(0)
                    df = pd.read_csv(file, encoding='latin1')
            else:
                df = pd.read_excel(file)
            
            # Normalize Headers
            df.columns = [c.strip() for c in df.columns]
            
            # Fuzzy Column Matching Logic
            cols = df.columns.str.lower()
            
            col_qty = next((c for c in df.columns if 'qty' in c.lower()), None)
            col_retail = next((c for c in df.columns if 'unit retail' in c.lower()), None) # Prioritize "Unit Retail"
            if not col_retail:
                 col_retail = next((c for c in df.columns if 'retail' in c.lower() and 'ext' not in c.lower()), None)
            
            col_ext_cost = next((c for c in df.columns if 'ext' in c.lower() and 'retail' in c.lower()), None) # Default standard
            # Fallback if standard format isn't found, try to find a 'Cost' column
            if not col_ext_cost:
                 col_ext_cost = next((c for c in df.columns if 'cost' in c.lower() and 'ext' in c.lower()), None)

            # Match Description Column for better variety check (optional)
            col_desc = next((c for c in df.columns if 'desc' in c.lower() or 'item' in c.lower() or 'product' in c.lower()), None)

            status = "OK"
            details = ""
            
            if not all([col_qty, col_retail, col_ext_cost]):
                status = "ERROR"
                details = f"Missing Columns. Found: {list(df.columns)}"
            else:
                # Clean Data
                df['Qty_Clean'] = pd.to_numeric(df[col_qty].apply(clean_currency), errors='coerce').fillna(0)
                df['Retail_Clean'] = pd.to_numeric(df[col_retail].apply(clean_currency), errors='coerce').fillna(0)
                df['Cost_Clean'] = pd.to_numeric(df[col_ext_cost].apply(clean_currency), errors='coerce').fillna(0)
                
                # Basic Calcs
                df['Total_Retail_Value'] = df['Qty_Clean'] * df['Retail_Clean']
            
            # Calculate Variety (Unique Lines with Qty > 0)
            if status == "OK":
                variety_count = len(df[df['Qty_Clean'] > 0])
            else:
                variety_count = 0

            # Package Summary
            summary = {
                'Filename': file.name,
                'Status': status,
                'Details': details,
                'Items': df['Qty_Clean'].sum() if status == "OK" else 0,
                'Variety': variety_count,
                'Total_Cost': df['Cost_Clean'].sum() if status == "OK" else 0,
                'Total_Retail': df['Total_Retail_Value'].sum() if status == "OK" else 0,
                'Raw_Data': df if status == "OK" else pd.DataFrame()
            }
            all_data.append(summary)

        except Exception as e:
            all_data.append({
                'Filename': file.name,
                'Status': "CRITICAL ERROR",
                'Details': str(e),
                'Items': 0, 'Variety': 0, 'Total_Cost': 0, 'Total_Retail': 0, 'Raw_Data': pd.DataFrame()
            })
            
    return pd.DataFrame(all_data)

# =========================================================
# UI LAYOUT
# =========================================================

# TITLE HEADER
st.markdown("""
<div style="text-align:left; margin-bottom: 20px;">
    <h1 style="background: linear-gradient(90deg, #00d4ff, #00fa9a); -webkit-background-clip: text; -webkit-text-fill-color: transparent; display: inline-block;">
        Margen Pro VIII
    </h1>
    <span style="color:#a0aab4; font-size: 1.2rem; margin-left: 15px;">Liquidator Elite Edition</span>
</div>
""", unsafe_allow_html=True)

# TABS
tab_analysis, tab_automation = st.tabs(["📊 Analysis Dashboard", "🤖 Auto-Sourcing (BETA)"])

# ---------------------------------------------------------
# TAB 1: ANALYSIS DASHBOARD
# ---------------------------------------------------------
with tab_analysis:
    # SIDEBAR CONTROLS
    with st.sidebar:
        st.header("⚙️ Simulation Settings")
        st.markdown("Adjust these sliders to model real-world scenarios.")
        
        st.subheader("Revenue Scenarios")
        discount_scenario = st.slider("Liquidation Sale Price (% of Retail)", 10, 100, 35, help="At what % of the original retail price will you sell the items?")
        
        st.subheader("Costs")
        freight_cost = st.number_input("Est. Freight Cost per Lot ($)", min_value=0.0, value=0.0, step=50.0)
        misc_cost = st.number_input("Misc/Labor Cost per Lot ($)", min_value=0.0, value=0.0, step=50.0)
        
        st.markdown("---")
        st.info(f"**Scenario Mode**: Selling items at **{discount_scenario}%** of Retail Value.")

    # FILE UPLOADER
    uploaded_files = st.file_uploader("Drop Manifest Files Here (CSV/Excel)", accept_multiple_files=True, type=['csv', 'xlsx', 'xls'])

    if uploaded_files:
        # PROCESS DATA
        df_summary = load_data(uploaded_files)
        
        # Filter valid data
        valid_packages = df_summary[df_summary['Status'] == "OK"].copy()
        
        if not valid_packages.empty:
            # AGGREGATE METRICS FOR SELECTED SCENARIO (GLOBAL)
            # Apply global costs multiplied by number of packages
            num_packages = len(valid_packages)
            total_freight = freight_cost * num_packages
            total_misc = misc_cost * num_packages
            
            total_purchase_cost = valid_packages['Total_Cost'].sum()
            total_retail_value = valid_packages['Total_Retail'].sum()
            
            # SCENARIO CALCULATIONS
            projected_revenue = total_retail_value * (discount_scenario / 100.0)
            total_expenses = total_purchase_cost + total_freight + total_misc
            projected_profit = projected_revenue - total_expenses
            roi = (projected_profit / total_expenses) * 100 if total_expenses > 0 else 0
            
            # ---------------------------------------------------------
            # 1. EXECUTIVE DASHBOARD
            # ---------------------------------------------------------
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Total Investment</div>
                    <div class="metric-value">${total_expenses:,.2f}</div>
                    <div style="font-size:0.8rem; color:#888;">Product + Freight + Misc</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col2:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Projected Revenue</div>
                    <div class="metric-value" style="color:#00d4ff;">${projected_revenue:,.2f}</div>
                    <div style="font-size:0.8rem; color:#888;">@ {discount_scenario}% of Retail</div>
                </div>
                """, unsafe_allow_html=True)

            with col3:
                color = "#00fa9a" if projected_profit > 0 else "#ff4b4b"
                st.markdown(f"""
                <div class="metric-card" style="border-color:{color};">
                    <div class="metric-label">Net Profit</div>
                    <div class="metric-value" style="background:none; color:{color};">${projected_profit:,.2f}</div>
                    <div style="font-size:0.8rem; color:#888;">Cash in Pocket</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col4:
                color = "#00fa9a" if roi > 20 else ("#ffbf00" if roi > 0 else "#ff4b4b")
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">ROI</div>
                    <div class="metric-value" style="background:none; color:{color};">{roi:,.1f}%</div>
                    <div style="font-size:0.8rem; color:#888;">Return on Investment</div>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("---")
            
            # ---------------------------------------------------------
            # 2. VISUAL ANALYTICS
            # ---------------------------------------------------------
            c1, c2 = st.columns([2, 1])
            
            with c1:
                st.subheader("💰 Financial Waterfall")
                # Waterfall Chart Logic
                fig_waterfall = go.Figure(go.Waterfall(
                    name = "20", orientation = "v",
                    measure = ["relative", "relative", "relative", "total"],
                    x = ["Sales Revenue", "Product Cost", "Overhead (Freight/Misc)", "Net Profit"],
                    textposition = "outside",
                    text = [f"${projected_revenue/1000:.1f}k", f"-${total_purchase_cost/1000:.1f}k", f"-${(total_freight+total_misc)/1000:.1f}k", f"${projected_profit/1000:.1f}k"],
                    y = [projected_revenue, -total_purchase_cost, -(total_freight+total_misc), projected_profit],
                    connector = {"line":{"color":"rgb(63, 63, 63)"}},
                ))
                fig_waterfall.update_layout(
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#e6e6e6'),
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=20)
                )
                st.plotly_chart(fig_waterfall, use_container_width=True)
                
            with c2:
                st.subheader("📦 Margin Analysis per File")
                # Calculate per-file metrics for the chart
                # Note: Freight/Misc is subtracted equally per file for the chart
                valid_packages['File_Revenue'] = valid_packages['Total_Retail'] * (discount_scenario / 100.0)
                valid_packages['File_Overhead'] = freight_cost + misc_cost
                valid_packages['File_Profit'] = valid_packages['File_Revenue'] - valid_packages['Total_Cost'] - valid_packages['File_Overhead']
                
                fig_bar = px.bar(
                    valid_packages, 
                    x='Filename', 
                    y=['Total_Cost', 'File_Profit'], 
                    title="",
                    barmode='group',
                    color_discrete_sequence=['#ff4b4b', '#00fa9a']
                )
                fig_bar.update_layout(
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#e6e6e6'),
                    legend=dict(orientation="h", y=1.1, title=None),
                    xaxis_title=None,
                    yaxis_title="$ USD",
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=20)
                )
                st.plotly_chart(fig_bar, use_container_width=True)

            # ---------------------------------------------------------
            # 3. DETAILED BREAKDOWN
            # ---------------------------------------------------------
            st.subheader("📋 Package Comparison")
            
            # Format for display
            display_df = valid_packages[['Filename', 'Items', 'Total_Cost', 'Total_Retail']].copy()
            
            # Add Variety if available
            if 'Variety' in valid_packages.columns:
                display_df['Variety (SKUs)'] = valid_packages['Variety']
            
            display_df['Projected Revenue'] = display_df['Total_Retail'] * (discount_scenario / 100.0)
            display_df['Net Profit'] = display_df['Projected Revenue'] - display_df['Total_Cost'] - (freight_cost + misc_cost)
            display_df['ROI'] = (display_df['Net Profit'] / (display_df['Total_Cost'] + freight_cost + misc_cost)) * 100
            
            # Reorder columns
            cols = ['Filename', 'Items', 'Total_Cost', 'Total_Retail', 'Projected Revenue', 'Net Profit', 'ROI']
            if 'Variety (SKUs)' in display_df.columns:
                cols.insert(2, 'Variety (SKUs)')
            
            display_df = display_df[cols]

            # Formatting
            st.dataframe(
                display_df.style.format({
                    'Total_Cost': "${:,.2f}",
                    'Total_Retail': "${:,.2f}",
                    'Projected Revenue': "${:,.2f}",
                    'Net Profit': "${:,.2f}",
                    'ROI': "{:,.1f}%"
                }).background_gradient(subset=['ROI'], cmap='RdYlGn', vmin=-20, vmax=100),
                use_container_width=True
            )

        else:
            st.warning("Could not process any valid files. Please check column headers.")
            st.write("Expected headers: 'Qty', 'Unit Retail', 'Ext. Retail' (or similar)")

    else:
        # EMPTY STATE
        st.markdown("""
        <div style="display:flex; justify-content:center; align-items:center; height:300px; border:2px dashed #333; border-radius:15px; margin-top:50px;">
            <div style="text-align:center; color:#666;">
                <h3 style="color:#888;">👋 Welcome to Margen Pro VIII</h3>
                <p>Drag and drop your manifest files to unlock insights.</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ---------------------------------------------------------
# TAB 2: AUTOMATION SCAFFOLD
# ---------------------------------------------------------
with tab_automation:
    st.header("🤖 Auto-Sourcing Bot (Coming Soon)")
    st.markdown("""
    This module will automatically scan retailer liquidation sites to find the best deals.
    
    **Supported Retailers (Planned):**
    - [ ] Walmart Liquidation
    - [ ] Costco
    - [ ] Target
    - [ ] JC Penney
    - [ ] Kohl's
    """)
    
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Walmart User ID")
        st.text_input("Walmart API Key")
    with c2:
        st.selectbox("Scan Frequency", ["Daily 8:00 AM", "Hourly", "Manual Only"])
    
    if st.button("🔴 Start Scraper (Simulation)"):
        st.warning("Web Scraper Module not yet connected. Please configure API keys.")
