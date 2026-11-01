def relative_humidity(temp_c, dew_c):

    if temp_c is None or dew_c is None:

        return None

    exponent = (

        17.625 * dew_c / (243.04 + dew_c)

        - 17.625 * temp_c / (243.04 + temp_c)

    )

    return max(0, min(100, 100 * math.exp(exponent)))

def isa_temp_c(altitude_ft):
    return 15 - 1.98 * altitude_ft / 1000

def pressure_altitude_ft(field_elevation_ft, qnh_hpa):
    if qnh_hpa is None or qnh_hpa <= 0: return None
    # Standard atmosphere inverse altimeter equation, approximate
    return field_elevation_ft + (1013.25 - qnh_hpa) * 27.0

def density_altitude_ft(pressure_altitude, temp_c):
    if pressure_altitude is None or temp_c is None: return None
    return pressure_altitude + 120 * (temp_c - isa_temp_c(pressure_altitude))

def wind_components(speed_kn, wind_from_true, runway_true):
    if any(v is None for v in (speed_kn, wind_from_true, runway_true)): return None, None
    angle = math.radians(wind_from_true - runway_true)
    return speed_kn * math.cos(angle), speed_kn * math.sin(angle)

def cloud_amount(total_pct):
    # Descriptive forecast proxy only; NEVER label this METAR FEW/SCT/BKN/OVC.
    if total_pct is None: return 'Unavailable'
    if total_pct < 12.5: return 'Mostly clear (model estimate)'
    if total_pct < 37.5: return 'Limited cover (model estimate)'
    if total_pct < 87.5: return 'Variable/substantial cover (model estimate)'
    return 'Near-complete cover (model estimate)'

def approximate_lcl_ft_agl(temp_c, dew_c):
    if temp_c is None or dew_c is None or dew_c > temp_c: return None
    return (temp_c - dew_c) * 400  # rough convective LCL only; NOT a cloud-base forecast
