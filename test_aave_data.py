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

def fetch_aave_data():
    aaves = {key: create_df(requests.get(f'https://yields.llama.fi/chartLendBorrow/{value}')) for key, value in pools.items()}
    return aaves['usdc-v3'], aaves['weth-v3']

usdc_df, weth_df = fetch_aave_data()
usdc_df['timestamp'] = usdc_df['timestamp'].dt.tz_localize(None)
weth_df['timestamp'] = weth_df['timestamp'].dt.tz_localize(None)


print(usdc_df[['timestamp', 'apyBaseBorrow']])