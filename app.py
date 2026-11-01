from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from airports import AIRPORTS
from data import MODELS, fetch_model, save_forecasts, save_observation, get_accuracy, fetch_vertical_profile, fetch_optional
from aviation import relative_humidity, isa_temp_c, pressure_altitude_ft, density_altitude_ft, cloud_amount, approximate_lcl_ft_agl

st.set_page_config(page_title='VFR Weather Intelligence', page_icon='🛩️', layout='wide')
st.title('🛩️ VFR Weather Intelligence v2.0')
st.caption('Experimental forecast analysis · NOT an official aviation briefing or a go/no-go decision tool')
with st.sidebar:
    st.header('Flight planning')
    airport = st.selectbox('Airport', list(AIRPORTS))
    lat, lon, elevation_ft, webcam_search = AIRPORTS[airport]
    st.caption(f'Approx. coordinates {lat:.4f}, {lon:.4f} · Field elevation {elevation_ft:,} ft')
    models = st.multiselect('Forecast models', list(MODELS), default=list(MODELS))
    hours = st.slider('Forecast horizon (hours)', 12, 72, 48, step=12)
    runway = st.number_input('Runway TRUE heading (°)', min_value=0, max_value=359, value=90, step=10, help='Enter the actual runway direction for crosswind calculations. No runway database is assumed.')
    st.caption('Enter runway TRUE bearing (not magnetic runway number). Model wind directions are true referenced. Gust components are not computed.')
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

# One shared valid-time control drives all selected-hour overview metrics.
reference_model = st.selectbox('Overview forecast model', list(frames), key='overview_model')
reference_frame = frames[reference_model]
valid_time = st.select_slider('Forecast valid time · Europe/Zurich',
    options=reference_frame['time'].tolist(),
    value=reference_frame['time'].iloc[min(3, len(reference_frame)-1)],
    format_func=lambda t: t.strftime('%a %d %b %H:%M'))
st.caption('All overview metrics below are model grid forecasts for this selected valid time, NOT current airport observations.')

# Snapshot only when explicitly requested, to prevent duplicates on every rerun.
if st.button('📸 Archive current forecast snapshot', help='Save the forecast now so it can later be checked against an independent observation.'):
    issued = save_forecasts(airport, frames)
    st.success(f'Forecast snapshot saved at {issued} UTC.')

st.subheader(f'{airport.split(" · ")[0]} · Forecast overview')
chosen = reference_frame
first = chosen.loc[chosen['time'] == valid_time].iloc[0]
cols = st.columns(4)
metrics = [
    ('Visibility forecast', f'{first.visibility_km:.1f} km' if pd.notna(first.visibility_km) else 'N/A'),
    ('Low cloud cover', f'{first.cloud_cover_low:.0f}%' if pd.notna(first.cloud_cover_low) else 'N/A'),
    ('Surface wind', f'{first.wind_speed_10m:.0f} kt' if pd.notna(first.wind_speed_10m) else 'N/A'),
    ('Gusts', f'{first.wind_gusts_10m:.0f} kt' if pd.notna(first.wind_gusts_10m) else 'N/A')]
for col, (label, value) in zip(cols, metrics): col.metric(label, value)
st.caption(f'Forecast: {reference_model} · valid {first.time:%d %b %H:%M} Europe/Zurich · Open-Meteo grid values, NOT measured airport reports.')

st.subheader('🌡️ Atmospheric conditions & performance estimates')
def fmt(row, field, unit='', decimals=1):
    value = row.get(field)
    return f'{float(value):.{decimals}f}{unit}' if pd.notna(value) else 'Unavailable'

t = float(first['temperature_2m']) if pd.notna(first.get('temperature_2m')) else None
td = float(first['dew_point_2m']) if pd.notna(first.get('dew_point_2m')) else None
mslp = float(first['pressure_msl']) if pd.notna(first.get('pressure_msl')) else None
sp = float(first['surface_pressure']) if pd.notna(first.get('surface_pressure')) else None
from math import exp

if t is not None and td is not None:

    exponent = (

        17.625 * td / (243.04 + td)

        - 17.625 * t / (243.04 + t)

    )

    rh = max(0.0, min(100.0, 100.0 * exp(exponent)))

else:

    rh = None
# Model MSL pressure is not airport QNH. For density altitude, use model surface pressure
# and standard-atmosphere conversion, not model MSL pressure as observed QNH.
pa = (145366.45 * (1 - (sp / 1013.25) ** 0.190284)) if sp and sp > 0 else None
da = density_altitude_ft(pa, t)
isa = isa_temp_c(elevation_ft)
metrics2 = [
 ('MSL pressure (model)', f'{mslp:.1f} hPa' if mslp is not None else 'Unavailable'),
 ('Surface pressure (model)', f'{sp:.1f} hPa' if sp is not None else 'Unavailable'),
 ('Temperature', fmt(first,'temperature_2m',' °C')),
 ('Dew point', fmt(first,'dew_point_2m',' °C')),
 ('Relative humidity', f'{rh:.0f}%' if rh is not None else 'Unavailable'),
 ('Wind FROM true', fmt(first,'wind_direction_10m','°',0)),
 ('ISA temperature at field', f'{isa:.1f} °C'),
 ('ISA deviation', f'{t-isa:+.1f} °C' if t is not None else 'Unavailable'),
 ('Pressure altitude (model)', f'{pa:,.0f} ft' if pa is not None else 'Unavailable'),
 ('Density altitude (model)', f'{da:,.0f} ft' if da is not None else 'Unavailable')]
for start in range(0,len(metrics2),5):
    cols2 = st.columns(5)
    for col,(label,value) in zip(cols2,metrics2[start:start+5]): col.metric(label,value)
st.caption('Pressure altitude and density altitude are approximate model-derived values at grid surface pressure. No observed QNH or POH aircraft performance calculation is implied. ISA uses 15°C at sea level and 1.98°C/1,000 ft.')

st.subheader('☁️ Cloud structure & freezing level')
cloudcols = st.columns(3)
cloudcols[0].metric('Low cloud (model)',fmt(first,'cloud_cover_low','%',0))
cloudcols[1].metric('Mid cloud (model)',fmt(first,'cloud_cover_mid','%',0))
cloudcols[2].metric('High cloud (model)',fmt(first,'cloud_cover_high','%',0))
st.write('**Total cloud-cover interpretation:**',cloud_amount(float(first['cloud_cover']) if pd.notna(first.get('cloud_cover')) else None))
st.caption('FEW/SCT/BKN/OVC are METAR/TAF layer terms, not derivable from total or low cloud percentage. Cloud bases and tops are unavailable unless a supported independent layer-specific source is connected.')
try:
    opt = fetch_optional(lat,lon,MODELS[reference_model])
    match = opt.loc[opt['time']==valid_time] if not opt.empty else opt
    if not match.empty:
        o = match.iloc[0]
        fr = o.get('freezing_level_height')
        if pd.notna(fr): st.metric('Model freezing level',f'{float(fr)*3.28084:,.0f} ft AMSL')
        else: st.info('Freezing-level field unavailable from this model.')
        base = o.get('cloud_base')
        if pd.notna(base): st.metric('Model cloud base (estimated)',f'{float(base)*3.28084:,.0f} ft AMSL')
        else: st.caption('Model cloud-base field unavailable; no base inferred from RH.')
    else: st.info('Freezing-level and cloud-base forecast fields unavailable for this model.')
except Exception as exc: st.info(f'Optional cloud/freezing fields unavailable: {str(exc)[:140]}')

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
st.subheader('🛠️ Carburettor icing risk reference')
st.caption('Temperature/dew-point reference chart with your selected airport forecast plotted as a moving marker. This concerns **carburettor icing**, not airframe icing.')
carb_model = st.selectbox('Carb icing chart model', list(frames), key='carb_model')
carb_frame = frames[carb_model].dropna(subset=['temperature_2m','dew_point_2m'])
if carb_frame.empty:
    st.info('Temperature and dew-point data unavailable for this model.')
else:
    carb_time = st.select_slider('Carb icing forecast hour (Europe/Zurich)', options=carb_frame['time'].tolist(),
        value=carb_frame['time'].iloc[min(3, len(carb_frame)-1)],
        format_func=lambda t: t.strftime('%a %d %b %H:%M'), key='carb_time')
    point = carb_frame.loc[carb_frame['time'] == carb_time].iloc[0]
    t, td = float(point['temperature_2m']), float(point['dew_point_2m'])
    from PIL import Image
    from pathlib import Path
    bg = Image.open(Path(__file__).with_name('carb_icing_plot.png'))
    chart = go.Figure()
    chart.add_layout_image(dict(source=bg, xref='x', yref='y', x=-20, y=30,
        sizex=60, sizey=50, sizing='stretch', opacity=1, layer='below'))
    chart.add_trace(go.Scatter(x=[t], y=[td], mode='markers+text',
        text=['● Forecast'], textposition='top center',
        marker=dict(size=19, color='#ef4444', line=dict(color='white', width=3)),
        name='Selected forecast', hovertemplate='Air temperature: %{x:.1f} °C<br>Dew point: %{y:.1f} °C<extra></extra>'))
    chart.update_layout(height=500, margin=dict(l=30,r=20,t=20,b=50),
        xaxis=dict(title='Air temperature (°C)', range=[-20,40], dtick=10, showgrid=False, zeroline=False),
        yaxis=dict(title='Dew point (°C)', range=[-20,30], dtick=10, showgrid=False, zeroline=False,
                   scaleanchor='x', scaleratio=1), showlegend=False)
    st.plotly_chart(chart, use_container_width=True)
    st.write(f'**{carb_model} · {carb_time:%d %b %H:%M} local:** air temperature **{t:.1f} °C**, dew point **{td:.1f} °C**, spread **{t-td:.1f} °C**.')
    timeline = carb_frame[['time','temperature_2m','dew_point_2m']].head(12).copy()
    timeline['spread_c'] = timeline['temperature_2m']-timeline['dew_point_2m']
    st.plotly_chart(px.line(timeline,x='time',y=['temperature_2m','dew_point_2m'],
        title='Next 12 forecast hours · temperature and dew point (°C)',
        labels={'value':'°C','time':'Local time','variable':'Variable'}),use_container_width=True)
    st.caption('This timeline is NOT a carb-icing risk classification. Consult the reference chart and the aircraft POH.')
    if not (-20 <= t <= 40 and -20 <= td <= 30):
        st.warning('The selected conditions fall outside the reference chart bounds. Do not infer a risk category from the image.')
    st.caption('The cropped background is the user-supplied qualitative carburettor icing reference. Colored regions depend on engine power and operating conditions; the marker is a **model forecast**, not a measured airport observation. The graphic is not a calibrated risk calculation and cannot establish a safe operating envelope. Follow the aircraft POH/AFM for carb heat and icing procedures.')

st.divider()
st.subheader('🧊 Vertical icing screening')
st.warning('**Not an icing forecast.** Temperature and relative humidity only flag altitude bands where icing *could* occur if supercooled liquid water is present. A low screening signal does NOT mean icing-free conditions. Use official icing products and avoid known icing in a non-FIKI C172.')
profile_model = st.selectbox('Vertical profile model', list(frames), key='profile_model')
forecast_times = frames[profile_model]['time'].tolist()
profile_time = st.select_slider('Forecast valid time (Europe/Zurich)', options=forecast_times,
                                 value=forecast_times[min(3, len(forecast_times)-1)],
                                 format_func=lambda t: t.strftime('%a %d %b %H:%M'))
try:
    profile = fetch_vertical_profile(lat, lon, MODELS[profile_model])
    if profile.empty:
        st.info('Pressure-level profile unavailable for this model/location.')
    else:
        slice_ = profile[profile['time'] == profile_time].sort_values('altitude_ft')
        slice_ = slice_[slice_['altitude_ft'] >= elevation_ft - 300].copy()
        if slice_.empty:
            st.info('No pressure-level profile available at the selected hour.')
        else:
            # Conservative *screening* proxy, NOT physical icing diagnosis.
            slice_['signal'] = slice_.apply(lambda r: 'Potential icing environment' if -20 <= r.temp_c <= 0 and r.rh_pct >= 90 else
                'Monitor: cold and humid' if -25 <= r.temp_c <= 2 and r.rh_pct >= 75 else 'Insufficient indication', axis=1)
            palette = {'Potential icing environment':'#e67e22', 'Monitor: cold and humid':'#eab308',
                       'Insufficient indication':'#94a3b8'}
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=slice_['temp_c'], y=slice_['altitude_ft'], mode='lines+markers',
                                     name='Temperature °C', line={'color':'#0284c7'},
                                     customdata=slice_[['rh_pct','level_hpa']],
                                     hovertemplate='%{y:,.0f} ft AMSL<br>%{x:.1f} °C<br>RH %{customdata[0]:.0f}%%<br>%{customdata[1]} hPa<extra></extra>'))
            for _, point in slice_.iterrows():
                fig.add_hrect(y0=point.altitude_ft-220, y1=point.altitude_ft+220,
                              fillcolor=palette[point.signal], opacity=.20, line_width=0)
            fig.add_vline(x=0, line_dash='dash', line_color='#0284c7')
            fig.update_layout(height=480, xaxis_title='Forecast temperature (°C)',
                              yaxis_title='Geopotential altitude (ft AMSL)', hovermode='closest')
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(slice_[['altitude_ft','level_hpa','temp_c','rh_pct','signal']].rename(columns={
                'altitude_ft':'Altitude ft AMSL','level_hpa':'Pressure hPa','temp_c':'Temperature °C',
                'rh_pct':'Relative humidity %','signal':'Screening indicator'}),
                hide_index=True, use_container_width=True)
            st.caption('Colored bands are pressure-level screening indicators, not cloud boundaries or certified icing probabilities. Interpolation between levels can miss thin layers. Model resolution and humidity uncertainty are significant.')
except Exception as e:
    st.info(f'Vertical profile unavailable: {str(e)[:220]}')

st.divider()
st.caption('Data: Open-Meteo forecast API and selected forecast models. Data availability, geographic coverage and forecast resolution vary by model. This dashboard is experimental, is not certified, and must not replace official METAR/TAF/GAFOR/SWC, NOTAMs, or pilot judgment.')