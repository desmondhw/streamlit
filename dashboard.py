import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
import warnings

# Suppress specific warning
warnings.filterwarnings("ignore", category=FutureWarning, module='_plotly_utils.basevalidators')

# Timezone conversion function
def convert_to_gmt8(df, column):
    tz = pytz.timezone('Asia/Singapore')
    df[column] = df[column].dt.tz_localize('UTC').dt.tz_convert(tz)
    return df

# Hyperliquid API function
def fetch_hyperliquid_funding(coin="BTC", days=7, hours_per_request=500):
    final_df = pd.DataFrame()
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    current_start_time = start_time

    while current_start_time < end_time:
        current_end_time = min(current_start_time + timedelta(hours=hours_per_request), end_time)
        start_time_millis = int(current_start_time.timestamp() * 1000)
        end_time_millis = int(current_end_time.timestamp() * 1000)
        payload = {"type": "fundingHistory", "coin": coin, "startTime": start_time_millis, "endTime": end_time_millis}
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
            # Log error instead of displaying
            print(f"Failed to fetch data: {response.status_code}")
            print(response.text)  # Log the response content for debugging
            break
        current_start_time = current_end_time

    final_df = convert_to_gmt8(final_df, 'time')  # Convert timezone to GMT+8
    return final_df

# Bitfinex API function
def fetch_bitfinex_funding(coin="tBTCF0:USTF0", days=7):
    url = f"https://api-pub.bitfinex.com/v2/status/deriv/{coin}/hist"
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    all_data = []
    headers = {"accept": "application/json"}

    while True:
        params = {"start": start_time, "end": end_time, "sort": 1, "limit": 5000}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            if not data:
                break
            all_data.extend(data)
            start_time = data[-1][0] + 1
        else:
            # Log error instead of displaying
            print(f"Failed to retrieve data: {response.status_code}")
            print(response.text)  # Log the response content for debugging
            break

    df = pd.DataFrame(all_data, columns=[
        "MTS", "NULL_1", "DERIV_PRICE", "SPOT_PRICE", "NULL_2", "INSURANCE_FUND_BALANCE", 
        "NULL_3", "NEXT_FUNDING_EVT_MTS", "NEXT_FUNDING_ACCRUED", "NEXT_FUNDING_STEP", 
        "NULL_4", "CURRENT_FUNDING", "NULL_5", "NULL_6", "MARK_PRICE", "NULL_7", 
        "NULL_8", "OPEN_INTEREST", "NULL_9", "NULL_10", "NULL_11", "CLAMP_MIN", "CLAMP_MAX"
    ])

    df['MTS'] = pd.to_datetime(df['MTS'], unit='ms')
    df['NEXT_FUNDING_EVT_MTS'] = pd.to_datetime(df['NEXT_FUNDING_EVT_MTS'], unit='ms')
    df = df[["MTS", "DERIV_PRICE", "SPOT_PRICE", "INSURANCE_FUND_BALANCE", 
             "NEXT_FUNDING_EVT_MTS", "NEXT_FUNDING_ACCRUED", "CURRENT_FUNDING", 
             "MARK_PRICE", "OPEN_INTEREST", "CLAMP_MIN", "CLAMP_MAX"]]

    df['Hour'] = df['MTS'].apply(lambda row: row.replace(minute=0, second=0, microsecond=0))
    grouped = df.groupby('Hour').agg(['first', 'last']).reset_index()
    grouped.columns = grouped.columns.map('_'.join).str.strip('_')
    grouped = grouped[['Hour', 'MTS_first', 'CURRENT_FUNDING_first', 'MTS_last', 'CURRENT_FUNDING_last']]

    grouped.rename(columns={
        'Hour': 'Hour Interval',
        'MTS_first': 'Interval Start Time',
        'CURRENT_FUNDING_first': 'Start Funding Rate',
        'MTS_last': 'Interval End Time',
        'CURRENT_FUNDING_last': 'End Funding Rate'
    }, inplace=True)

    grouped['Annualized Funding Rate'] = grouped['End Funding Rate'] * 3 * 365 * 100

    grouped = convert_to_gmt8(grouped, 'Hour Interval')  # Convert timezone to GMT+8
    return grouped

# Title
st.title("Funding Rate Dashboard")

# Create dropdowns for coin and days
col1, col2 = st.columns([1, 3])
with col1:
    coin = st.selectbox("Select Coin", ["BTC", "ETH", "SOL"], key='coin')
with col2:
    days = st.slider("Select Days", min_value=1, max_value=90, value=7, key='days')

# Fetch data
hyperliquid_df = fetch_hyperliquid_funding(coin=coin, days=days)
bitfinex_df = fetch_bitfinex_funding(coin=f"t{coin}F0:USTF0", days=days)

# Calculate differences
if not hyperliquid_df.empty and not bitfinex_df.empty:
    hyperliquid_avg = hyperliquid_df['annualizedFundingRate'].mean()
    bitfinex_avg = bitfinex_df['Annualized Funding Rate'].mean()
    difference = hyperliquid_avg - bitfinex_avg

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
            {round(hyperliquid_avg, 2)}%
            <div class="stat-label">Average Hyperliquid Funding Rate</div>
        </div>
        <div class="stat">
            {round(bitfinex_avg, 2)}%
            <div class="stat-label">Average Bitfinex Funding Rate</div>
        </div>
        <div class="stat">
            {round(difference, 2)}%
            <div class="stat-label">Difference</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Calculate funding rate difference
    combined_df = pd.merge_asof(hyperliquid_df[['time', 'annualizedFundingRate']], bitfinex_df[['Hour Interval', 'Annualized Funding Rate']],
                                left_on='time', right_on='Hour Interval', direction='nearest')
    combined_df['Funding Rate Difference'] = combined_df['annualizedFundingRate'] - combined_df['Annualized Funding Rate']

    # Plot funding rate difference
    fig_diff = go.Figure()
    fig_diff.add_trace(go.Scatter(x=combined_df['time'], y=combined_df['Funding Rate Difference'],
                                  mode='lines', name='Funding Rate Difference', line=dict(color='#FF0000')))
    fig_diff.update_layout(title='Funding Rate Difference (Hyperliquid - Bitfinex)', xaxis_title='Time', yaxis_title='Funding Rate Difference')
    st.plotly_chart(fig_diff, use_container_width=True)

    # Plot Hyperliquid funding rate
    fig_hyperliquid = go.Figure()
    fig_hyperliquid.add_trace(go.Scatter(x=hyperliquid_df['time'], y=hyperliquid_df['annualizedFundingRate'],
                                         mode='lines', name='Hyperliquid', line=dict(color='#00BFFF')))
    fig_hyperliquid.update_layout(title='Hyperliquid Annualized Funding Rate', xaxis_title='Time', yaxis_title='Annualized Funding Rate')
    st.plotly_chart(fig_hyperliquid, use_container_width=True)

    # Plot Bitfinex funding rate
    fig_bitfinex = go.Figure()
    fig_bitfinex.add_trace(go.Scatter(x=bitfinex_df['Hour Interval'], y=bitfinex_df['Annualized Funding Rate'],
                                      mode='lines', name='Bitfinex', line=dict(color='#4682B4')))
    fig_bitfinex.update_layout(title='Bitfinex Annualized Funding Rate', xaxis_title='Time', yaxis_title='Annualized Funding Rate')
    st.plotly_chart(fig_bitfinex, use_container_width=True)

else:
    st.warning("No data available to display")

# Auto-refresh every hour
if st.button('Refresh Now'):
    st.rerun()

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
