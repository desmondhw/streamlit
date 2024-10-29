import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go

# AAVE Arbitrum pool
pools = {
    'usdc-v3': 'd9fa8e14-0447-4207-9ae8-7810199dfa1f',
    'weth-v3': 'e302de4d-952e-4e18-9749-0a9dc86e98bc',
}

# Function to create a DataFrame from the AAVE API response
def create_df(aave_df):
    aave_df = pd.DataFrame(aave_df.json()['data'])
    aave_df['timestamp'] = pd.to_datetime(aave_df['timestamp'], utc=True)  # Ensure timestamps are in UTC
    aave_df['timestamp'] = aave_df['timestamp'].dt.tz_convert('Asia/Singapore')  # GMT+8 timezone
    return aave_df

# Fetch data for both pools
@st.cache_data(ttl=600)
def fetch_aave_data():
    aaves = {key: create_df(requests.get(f'https://yields.llama.fi/chartLendBorrow/{value}')) for key, value in pools.items()}
    return aaves['usdc-v3'], aaves['weth-v3']

# Function to convert datetime to milliseconds since epoch
def datetime_to_millis(dt):
    return int(dt.timestamp() * 1000)

# Hyperliquid API function with pagination and controlled request size
def fetch_hyperliquid_funding(coin="ETH", days=7, hours_per_request=500):
    final_df = pd.DataFrame()
    tz = pytz.timezone('Asia/Singapore')
    # Set the end time as now in GMT+8
    end_time = datetime.now(tz).replace(hour=7, minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(days=days)
    
    current_start_time = start_time
    while current_start_time < end_time:
        current_end_time = min(current_start_time + timedelta(hours=hours_per_request), end_time)
        start_time_millis = datetime_to_millis(current_start_time)
        end_time_millis = datetime_to_millis(current_end_time)
        
        # Request payload
        payload = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_time_millis,
            "endTime": end_time_millis
        }
        url = 'https://api.hyperliquid.xyz/info'
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            batch_df = pd.DataFrame(data)
            batch_df['time'] = pd.to_datetime(batch_df['time'], unit='ms')
            batch_df['fundingRate'] = pd.to_numeric(batch_df['fundingRate'], errors='coerce')
            batch_df['annualizedFundingRate'] = batch_df['fundingRate'] * 24 * 365 * 100
            final_df = pd.concat([final_df, batch_df], ignore_index=True)
        else:
            print(f"Failed to fetch data: {response.status_code}")
            break
        current_start_time = current_end_time

    return final_df

# Function to merge Hyperliquid and AAVE data on timestamp
def merge_data(hyperliquid_df, usdc_df, weth_df):
    # Ensure both AAVE and Hyperliquid timestamps are in UTC without timezones
    usdc_df['timestamp'] = usdc_df['timestamp'].dt.tz_localize(None)
    weth_df['timestamp'] = weth_df['timestamp'].dt.tz_localize(None)
    
    # Merge the funding data with the USDC borrow and WETH lend rates
    merged_df = pd.merge_asof(hyperliquid_df.sort_values('time'), usdc_df[['timestamp', 'apyBaseBorrow']].sort_values('timestamp'),
                              left_on='time', right_on='timestamp', direction='backward')
    merged_df = pd.merge_asof(merged_df, weth_df[['timestamp', 'apyBase']].sort_values('timestamp'),
                              left_on='time', right_on='timestamp', direction='backward')

    # Rename columns for clarity
    merged_df = merged_df.rename(columns={'apyBaseBorrow': 'usdc_borrow_rate', 'apyBase': 'weth_lend_rate'})
    
    # Drop the extra 'timestamp' columns from the merges
    merged_df = merged_df.drop(columns=['timestamp_x', 'timestamp_y'])

    return merged_df

# Fetching and processing data
st.title("Aave-HL Arb Dashboard")

# Create input widgets for coin, days, Leverage, and LTV with adjusted column widths
col1, col2, col3, col4 = st.columns([2, 2, 1, 1])  # Adjusted widths
with col1:
    coin = st.selectbox("Select Coin", ["ETH"], key='coin')
with col2:
    days = st.slider("Select Days", min_value=1, max_value=365, value=7, key='days')
with col3:
    leverage = st.number_input("Leverage", min_value=0.1, max_value=10.0, value=1.0, step=0.1, key='leverage')
with col4:
    ltv = st.number_input("LTV", min_value=0.0, max_value=1.0, value=0.67, step=0.01, key='ltv')

# Main Execution
# Fetch Hyperliquid funding data
hyperliquid_df = fetch_hyperliquid_funding(coin="ETH", days=days, hours_per_request=500)

# Fetch AAVE data for USDC and WETH
usdc_df, weth_df = fetch_aave_data()

# Merge Hyperliquid data with AAVE data based on timestamps
merged_df = merge_data(hyperliquid_df, usdc_df, weth_df)

# Adjust usdc_borrow_rate and weth_lend_rate based on Leverage and LTV
merged_df['adjusted_usdc_borrow_rate'] = merged_df['usdc_borrow_rate'] * leverage * ltv
merged_df['adjusted_weth_lend_rate'] = merged_df['weth_lend_rate'] * leverage
merged_df['annualizedFundingRate'] = merged_df['annualizedFundingRate'] * leverage

# Calculate arb_return using adjusted rates
merged_df['arb_return'] = merged_df['annualizedFundingRate'] + merged_df['adjusted_weth_lend_rate'] - merged_df['adjusted_usdc_borrow_rate']

# Display statistics
if not merged_df.empty:
    hyperliquid_avg = merged_df['annualizedFundingRate'].mean()
    adjusted_weth_lend_avg = merged_df['adjusted_weth_lend_rate'].mean()
    adjusted_usdc_borrow_avg = merged_df['adjusted_usdc_borrow_rate'].mean()
    arb = merged_df['arb_return'].mean()

    # Display statistics in a styled format
    st.markdown("""
    <style>
    .stat-container {
        display: flex;
        justify-content: space-around;
        padding: 20px 0;
    }
    .stat {
        text-align: center;
        font-size: 24px;
        font-weight: bold;
        margin: 10px;
    }
    .stat-label {
        font-size: 14px;
        color: grey;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="stat-container">
        <div class="stat">
            {round(arb, 2)}%
            <div class="stat-label">Average Arb Return</div>
        </div>
        <div class="stat">
            {round(hyperliquid_avg, 2)}%
            <div class="stat-label">Average Hyperliquid Funding Rate</div>
        </div>
        <div class="stat">
            {round(adjusted_usdc_borrow_avg, 2)}%
            <div class="stat-label">Average AAVE USDC Borrow Rate</div>
        </div>
        <div class="stat">
            {round(adjusted_weth_lend_avg, 2)}%
            <div class="stat-label">Average AAVE WETH Lending Rate</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Plot Arb Return
    fig_arb = go.Figure()
    fig_arb.add_trace(go.Scatter(x=merged_df['time'], y=merged_df['arb_return'],
                                  mode='lines', name='Arb Return', line=dict(color='#FF0000')))
    fig_arb.update_layout(title='Arb Return', xaxis_title='Time', yaxis_title='Arb Return (%)')
    st.plotly_chart(fig_arb, use_container_width=True)

    # Plot Hyperliquid funding rate
    fig_hyperliquid = go.Figure()
    fig_hyperliquid.add_trace(go.Scatter(x=merged_df['time'], y=merged_df['annualizedFundingRate'],
                                         mode='lines', name='Hyperliquid', line=dict(color='#00BFFF')))
    fig_hyperliquid.update_layout(title='Hyperliquid Annualized Funding Rate', xaxis_title='Time', yaxis_title='Annualized Funding Rate (%)')
    st.plotly_chart(fig_hyperliquid, use_container_width=True)

    # Plot Adjusted USDC Borrow Rate
    fig_usdc = go.Figure()
    fig_usdc.add_trace(go.Scatter(x=merged_df['time'], y=merged_df['adjusted_usdc_borrow_rate'],
                                      mode='lines', name='USDC Borrow Rate', line=dict(color='#4682B4')))
    fig_usdc.update_layout(title='USDC Borrow Rate', xaxis_title='Time', yaxis_title='Annualized Borrow Rate (%)')
    st.plotly_chart(fig_usdc, use_container_width=True)

    # Plot Adjusted WETH Lending Rate
    fig_weth = go.Figure()
    fig_weth.add_trace(go.Scatter(x=merged_df['time'], y=merged_df['adjusted_weth_lend_rate'],
                                      mode='lines', name='WETH Lending Rate', line=dict(color='#4682B4')))
    fig_weth.update_layout(title='WETH Lending Rate', xaxis_title='Time', yaxis_title='Annualized Lending Rate (%)')
    st.plotly_chart(fig_weth, use_container_width=True)

else:
    st.warning("No data available to display")

# Auto-refresh every hour
if st.button('Refresh Now'):
    st.experimental_rerun()

# Set up a timer to refresh every hour
st.markdown(
    """
    <script>
    function refresh() {
        window.location.reload();
    }
    setTimeout(refresh, 3600000); // 3600000 milliseconds = 1 hour
    </script>
    """,
    unsafe_allow_html=True
)