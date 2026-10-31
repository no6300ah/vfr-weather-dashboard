import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
import streamlit as st

DB = Path(__file__).with_name('aviation_weather.sqlite3')
BASE = 'https://api.open-meteo.com/v1/forecast'
MODELS = {'ICON D2': 'icon_d2', 'ECMWF IFS': 'ecmwf_ifs025', 'GFS': 'gfs_global'}
HOURLY = ['visibility', 'cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high', 'cloud_cover', 'wind_speed_10m', 'wind_gusts_10m', 'wind_direction_10m', 'relative_humidity_2m', 'temperature_2m', 'dew_point_2m', 'pressure_msl']

@st.cache_data(ttl=900, show_spinner=False)
def fetch_model(lat, lon, model):
    params = {'latitude': lat, 'longitude': lon, 'models': model, 'hourly': ','.join(HOURLY), 'timezone': 'Europe/Zurich', 'forecast_days': 4, 'wind_speed_unit': 'kn', 'temperature_unit': 'celsius'}
    r = requests.get(BASE, params=params, timeout=25)
    r.raise_for_status()
    payload = r.json()
    if 'hourly' not in payload: raise ValueError('Forecast hourly data missing')
    h = payload['hourly']
    df = pd.DataFrame(h)
    # When a single model is selected, Open-Meteo may suffix hourly keys with model names.
    rename = {col: next((v for v in HOURLY if col == v or col.startswith(v + '_')), col) for col in df.columns if col != 'time'}
    df = df.rename(columns=rename)
    df['time'] = pd.to_datetime(df['time'])
    df['visibility_km'] = pd.to_numeric(df.get('visibility'), errors='coerce') / 1000
    df['model'] = next((k for k, v in MODELS.items() if v == model), model)
    return df

def connect():
    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS forecasts (
        airport TEXT NOT NULL, model TEXT NOT NULL, issued_utc TEXT NOT NULL,
        valid_local TEXT NOT NULL, visibility_km REAL, low_cloud_pct REAL,
        wind_kn REAL, gust_kn REAL,
        PRIMARY KEY (airport, model, issued_utc, valid_local))''')
    con.execute('''CREATE TABLE IF NOT EXISTS observations (
        airport TEXT NOT NULL, valid_local TEXT NOT NULL, observed_utc TEXT NOT NULL,
        visibility_km REAL, fog_present INTEGER, notes TEXT,
        PRIMARY KEY (airport, valid_local))''')
    return con

def save_forecasts(airport, frames):
    issued = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connect() as con:
        for model, df in frames.items():
            for _, r in df.iterrows():
                con.execute('INSERT OR IGNORE INTO forecasts VALUES (?,?,?,?,?,?,?,?)', (
                    airport, model, issued, r['time'].strftime('%Y-%m-%d %H:%M'),
                    _num(r.get('visibility_km')), _num(r.get('cloud_cover_low')),
                    _num(r.get('wind_speed_10m')), _num(r.get('wind_gusts_10m'))))
    return issued

def _num(value):
    return None if pd.isna(value) else float(value)

def save_observation(airport, valid_local, visibility_km, fog_present, notes):
    with connect() as con:
        con.execute('INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)', (
            airport, valid_local, datetime.now(timezone.utc).isoformat(timespec='seconds'),
            float(visibility_km) if visibility_km is not None else None,
            int(fog_present), notes))

def get_accuracy(airport):
    with connect() as con:
        df = pd.read_sql_query('''SELECT f.model, f.issued_utc, f.valid_local, f.visibility_km AS predicted_km,
              o.visibility_km AS observed_km, o.fog_present
              FROM forecasts f JOIN observations o ON f.airport=o.airport AND f.valid_local=o.valid_local
              WHERE f.airport=? AND f.visibility_km IS NOT NULL AND o.visibility_km IS NOT NULL''', con, params=(airport,))
    if df.empty: return df
    # Use the most recent snapshot issued before the forecast valid time, at least 1h ahead.
    df['lead_h'] = (pd.to_datetime(df['valid_local']).dt.tz_localize('Europe/Zurich', ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC') - pd.to_datetime(df['issued_utc'], utc=True)).dt.total_seconds()/3600
    df = df[df['lead_h'] >= 1].copy()
    if df.empty: return df
    df = df.sort_values('issued_utc').drop_duplicates(['model', 'valid_local'], keep='last')
    df['abs_error_km'] = (df['predicted_km'] - df['observed_km']).abs()
    df['predicted_low_visibility'] = df['predicted_km'] < 5
    df['observed_low_visibility'] = df['observed_km'] < 5
    df['low_vis_correct'] = df['predicted_low_visibility'] == df['observed_low_visibility']
    return df