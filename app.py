from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from airports import AIRPORTS
from data import MODELS, fetch_model, save_forecasts, save_observation, get_accuracy

st.set_page_config(page_title='VFR Weather Intelligence', page_icon='🛩️', layout='wide')
st.title('🛩️ VFR Weather Intelligence')
st.caption('Experimental forecast analysis · NOT an official aviation briefing or a go/no-go decision tool')
with st.sidebar:
    st.header('Flight planning')
    airport = st.selectbox('Airport', list(AIRPORTS))
    lat, lon, elevation_ft, webcam_search = AIRPORTS[airport]
    st.caption(f'Approx. coordinates {lat:.4f}, {lon:.4f} · Field elevation {elevation_ft:,} ft')
    models = st.multiselect('Forecast models', list(MODELS), default=list(MODELS))
    hours = st.slider('Forecast horizon (hours)', 12, 72, 48, step=12)
    runway = st.number_input('Runway magnetic heading (°)', min_value=0, max_value=359, value=90, step=10, help='Enter the actual runway direction for crosswind calculations. No runway database is assumed.')
    st.caption('Wind directions from weather models are true-north referenced. Crosswind estimates are approximate until runway true bearing is used; magnetic variation is not automatically corrected.')
    if st.button('Refresh data', use_container_width=True): st.cache_data.clear()

if not models:
    st.info('Select at least one model in the sidebar.'); st.stop()

frames = {}
errors = {}
with st.spinner('Retrieving forecast model data…'):
    for name in models:
        try:
            df = fetch_model(lat, lon, MODELS[name])
            frames[name] = df.head(hours).copy()
        except Exception as e:
            errors[name] = str(e)
for name, err in errors.items(): st.warning(f'{name} unavailable: {err[:240]}')
if not frames:
    st.error('No model data could be loaded. Check your internet connection, or try another model.'); st.stop()

# Snapshot only when explicitly requested, to prevent duplicates on every rerun.
if st.button('📸 Archive current forecast snapshot', help='Save the forecast now so it can later be checked against an independent observation.'):
    issued = save_forecasts(airport, frames)
    st.success(f'Forecast snapshot saved at {issued} UTC.')

st.subheader(f'{airport.split(" · ")[0]} · Forecast overview')
chosen = next(iter(frames.values()))
first = chosen.iloc[0]
cols = st.columns(4)
metrics = [
    ('Visibility forecast', f'{first.visibility_km:.1f} km' if pd.notna(first.visibility_km) else 'N/A'),
    ('Low cloud cover', f'{first.cloud_cover_low:.0f}%' if pd.notna(first.cloud_cover_low) else 'N/A'),
    ('Surface wind', f'{first.wind_speed_10m:.0f} kt' if pd.notna(first.wind_speed_10m) else 'N/A'),
    ('Gusts', f'{first.wind_gusts_10m:.0f} kt' if pd.notna(first.wind_gusts_10m) else 'N/A')]
for col, (label, value) in zip(cols, metrics): col.metric(label, value)
st.caption(f'Values are from {next(iter(frames))}, first forecast hour ({first.time:%d %b %H:%M} local). Airport-grid forecast, NOT a measured airport report.')

long = pd.concat(frames.values(), ignore_index=True)
tab1, tab2, tab3, tab4 = st.tabs(['🌫️ Fog & visibility', '🌬️ Wind & gusts', '📷 Webcams', '📊 Forecast accuracy'])
with tab1:
    st.markdown('**Visibility forecast comparison**')
    fig = px.line(long, x='time', y='visibility_km', color='model', labels={'time':'Local time (Europe/Zurich)','visibility_km':'Visibility (km)','model':'Model'})
    fig.add_hline(y=5, line_dash='dash', annotation_text='5 km reference (not a VFR clearance)')
    fig.update_layout(hovermode='x unified', height=370)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('**Low cloud cover comparison**')
    fig = px.line(long, x='time', y='cloud_cover_low', color='model', labels={'time':'Local time','cloud_cover_low':'Low cloud cover (%)','model':'Model'})
    fig.update_yaxes(range=[0, 100]); fig.update_layout(hovermode='x unified', height=320)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('**Possible visibility recovery**')
    for name, df in frames.items():
        low = df[df['visibility_km'] < 5]
        if low.empty: st.write(f'**{name}:** No forecast hours below 5 km in selected window.')
        else:
            last_low = low['time'].max()
            later = df[(df['time'] > last_low) & (df['visibility_km'] >= 5)]
            if later.empty: st.write(f'**{name}:** Visibility remains below 5 km at some point through the end of the window; no final recovery identified.')
            else: st.write(f'**{name}:** Last forecast sub-5-km hour {last_low:%d %b %H:%M}; next recovery hour {later.iloc[0]["time"]:%d %b %H:%M}.')
    st.info('5 km is an analysis threshold only. Fog, low stratus, cloud base, terrain, airspace and legal VMC minima require independent assessment. Model grid cells may miss localized fog at LSZN.')
with tab2:
    fig = go.Figure()
    for name, df in frames.items():
        fig.add_trace(go.Scatter(x=df.time, y=df.wind_speed_10m, name=f'{name} wind', mode='lines'))
        fig.add_trace(go.Scatter(x=df.time, y=df.wind_gusts_10m, name=f'{name} gust', mode='lines', line={'dash':'dot'}))
    fig.update_layout(title='10 m wind and gusts (kt)', xaxis_title='Local time', yaxis_title='Knots', hovermode='x unified', height=390)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('**Approximate runway wind components**')
    import numpy as np
    wind = chosen.copy()
    # Model wind direction is meteorological true direction. Runway bearing input must be true for accurate result.
    angle = np.deg2rad(wind['wind_direction_10m'] - runway)
    wind['Headwind (kt)'] = (wind['wind_speed_10m'] * np.cos(angle)).round(1)
    wind['Crosswind absolute (kt)'] = (wind['wind_speed_10m'] * np.sin(angle)).abs().round(1)
    st.dataframe(wind[['time', 'wind_direction_10m', 'wind_speed_10m', 'wind_gusts_10m', 'Headwind (kt)', 'Crosswind absolute (kt)']].head(24).rename(columns={'time':'Local time','wind_direction_10m':'Wind from (° true)','wind_speed_10m':'Wind (kt)','wind_gusts_10m':'Gusts (kt)'}), hide_index=True, use_container_width=True)
    st.caption('Runway heading is user-entered. Model winds are true referenced, and no magnetic variation correction is applied. Components use steady wind, not gusts.')
with tab3:
    st.write('Webcam links are discovery links, not verified live camera feeds. Check camera location, elevation, direction, timestamp and image age before using them.')
    st.link_button(f'Search webcams near {airport.split(" · ")[0]}', webcam_search)
    st.link_button('Windy webcams map', 'https://www.windy.com/webcams')
    st.link_button('MeteoSwiss satellite imagery', 'https://www.meteoswiss.admin.ch/weather/satellite-images.html')
    st.markdown('**Manual observation log**')
    st.write('When you inspect a timestamped webcam or obtain a reliable local report, log what you actually observed. This is how the dashboard can later score its forecasts.')
    with st.form('observation'):
        obs_date = st.date_input('Observation date (local)', value=datetime.now().date())
        obs_hour = st.selectbox('Observation hour (Europe/Zurich)', list(range(24)), index=datetime.now().hour)
        obs_vis = st.number_input('Observed visibility (km)', min_value=0.0, max_value=100.0, value=5.0, step=0.5, help='Enter only a measured or defensibly reported value. Do not infer precise km from a webcam image.')
        obs_fog = st.checkbox('Fog observed / reported')
        obs_note = st.text_input('Source and notes (recommended)', placeholder='e.g. official observation, timestamp, camera direction')
        submit = st.form_submit_button('Save observation')
    if submit:
        valid = f'{obs_date:%Y-%m-%d} {obs_hour:02d}:00'
        save_observation(airport, valid, obs_vis, obs_fog, obs_note)
        st.success(f'Saved observation for {valid} local time.')
with tab4:
    st.write('Accuracy is calculated only from **archived predictions** paired with **independently entered local observations**. It does not silently treat historical model data as truth.')
    acc = get_accuracy(airport)
    if acc.empty:
        st.info('No comparable samples yet. Archive a forecast now, then log a real observation for a matching future hour (at least one hour after snapshot).')
    else:
        summary = acc.groupby('model').agg(samples=('abs_error_km','size'), mean_absolute_error_km=('abs_error_km','mean'), low_visibility_classification_accuracy=('low_vis_correct','mean')).reset_index()
        summary['mean_absolute_error_km'] = summary['mean_absolute_error_km'].round(2)
        summary['low_visibility_classification_accuracy'] = (summary['low_visibility_classification_accuracy']*100).round(1)
        st.dataframe(summary.rename(columns={'model':'Model','samples':'Matched hours','mean_absolute_error_km':'Visibility MAE (km)','low_visibility_classification_accuracy':'Below/above 5 km accuracy (%)'}), hide_index=True, use_container_width=True)
        st.plotly_chart(px.scatter(acc, x='observed_km', y='predicted_km', color='model', hover_data=['valid_local','lead_h'], labels={'observed_km':'Observed visibility (km)','predicted_km':'Forecast visibility (km)'}), use_container_width=True)
        st.download_button('Download matched forecast/observation data', acc.to_csv(index=False), file_name='forecast_accuracy.csv', mime='text/csv')
        st.caption('Small samples and manually estimated observations can be misleading. Forecasts are selected as the latest snapshot at least 1 hour before valid time.')

st.divider()
st.caption('Data: Open-Meteo forecast API and selected forecast models. Data availability, geographic coverage and forecast resolution vary by model. This dashboard is experimental, is not certified, and must not replace official METAR/TAF/GAFOR/SWC, NOTAMs, or pilot judgment.')