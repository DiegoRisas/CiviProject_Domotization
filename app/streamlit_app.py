from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

# --- Configuración de página ---
st.set_page_config(
    page_title="Panel 24h · Domótica y Energía",
    page_icon="⚡",
    layout="wide",
)

# Cambia DEV por PRO cuando despliegues Fase 2 a producción
DEVICES_TABLE = "DOMO_DEV_GOLD_DB.CORE.DIM_DISPOSITIVOS"
SOURCE_VIEW = "DOMO_DEV_GOLD_DB.ENERGIA.MART_PANEL_TERMO_24H"
MONTHLY_VIEW = "DOMO_DEV_GOLD_DB.ENERGIA.MART_RESUMEN_MENSUAL_TERMO"

session = get_active_session()


@st.cache_data(ttl=300)
def load_devices(table_name: str) -> pd.DataFrame:
    df_d = session.sql(f"SELECT * FROM {table_name} ORDER BY DISPOSITIVO_ID").to_pandas()
    df_d.columns = [c.lower() for c in df_d.columns]
    return df_d


@st.cache_data(ttl=300)
def load_data(view_name: str) -> pd.DataFrame:
    df = session.sql(f"SELECT * FROM {view_name} ORDER BY FECHA, HORA").to_pandas()
    df.columns = [c.lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    return df


@st.cache_data(ttl=300)
def load_monthly(view_name: str) -> pd.DataFrame:
    df_m = session.sql(f"SELECT * FROM {view_name} ORDER BY FECHA DESC").to_pandas()
    df_m.columns = [c.lower() for c in df_m.columns]
    df_m["fecha"] = pd.to_datetime(df_m["fecha"]).dt.date
    return df_m


df_devices = load_devices(DEVICES_TABLE)
df = load_data(SOURCE_VIEW)
df_mes = load_monthly(MONTHLY_VIEW)

if df_devices.empty or df.empty:
    st.warning("Faltan datos en DIM_DISPOSITIVOS o MART_PANEL_TERMO_24H.")
    st.stop()

# --- Regla de las 21:00 (Europe/Madrid) ---
now_madrid = datetime.now(ZoneInfo("Europe/Madrid"))
default_date = (
    (now_madrid + timedelta(days=1)).date()
    if now_madrid.hour >= 21
    else now_madrid.date()
)

fechas_disponibles = sorted(df["fecha"].unique(), reverse=True)
if default_date in fechas_disponibles:
    default_index = fechas_disponibles.index(default_date)
    aviso_auto = (
        f"Auto ({now_madrid.strftime('%H:%M')}): "
        f"{'mostrando mañana (≥ 21:00)' if now_madrid.hour >= 21 else 'mostrando hoy (< 21:00)'}"
    )
else:
    default_index = 0
    aviso_auto = f"Fecha objetivo ({default_date}) aún no disponible; mostrando último día cargado."

# --- Cabecera y selectores (Dispositivo + Día) ---
col_title, col_dev, col_date, col_btn = st.columns([2.6, 1.4, 1.1, 0.7])

with col_title:
    st.title("⚡ Panel 24h · Energía Hogar")
    st.caption(aviso_auto)

with col_dev:
    dispositivos_ids = df_devices["dispositivo_id"].tolist()
    labels_disp = {
        row["dispositivo_id"]: f"{row['nombre_dispositivo']} ({row['habitacion']})"
        for _, row in df_devices.iterrows()
    }
    disp_sel = st.selectbox(
        "Dispositivo",
        options=dispositivos_ids,
        format_func=lambda x: labels_disp.get(x, x),
    )

with col_date:
    fecha_sel = st.selectbox(
        "Seleccionar día",
        options=fechas_disponibles,
        index=default_index,
        format_func=lambda d: d.strftime("%d/%m/%Y"),
    )

with col_btn:
    st.write("")
    if st.button("🔄 Recargar"):
        st.cache_data.clear()
        st.rerun()

# Datos del dispositivo seleccionado
dev_info = df_devices[df_devices["dispositivo_id"] == disp_sel].iloc[0]
tipo_disp = dev_info["tipo_dispositivo"]
potencia_kw = float(dev_info["potencia_nominal_kw"])
horas_base = int(dev_info["horas_base_dia"])
habitacion = str(dev_info["habitacion"])
temp_obj = dev_info.get("temp_confort_objetivo_c")

# Ficha técnica rápida desde DIM_DISPOSITIVOS
info_extra = f" · Confort objetivo: **{temp_obj:.1f} °C**" if pd.notna(temp_obj) else ""
st.info(
    f"📍 Habitación: **{habitacion}** · Tipo: `{tipo_disp}` · "
    f"Potencia: **{potencia_kw:.2f} kW** · Uso base: **{horas_base} h/día**{info_extra}"
)

# --- Preparar dataframe horario según el dispositivo ---
df_day = df[df["fecha"] == fecha_sel].sort_values("hora").copy()
df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

if tipo_disp == "termo":
    # Usa directamente el plan optimizado por bloques + frío de Gold
    df_plan = df_day.copy()
    df_plan["estado_disp"] = df_plan["estado_termo"]
else:
    # Estimación previa para calefactores/electrodomésticos usando las N horas PVPC más baratas
    # (en Bloque 3 se sustituirá por fct_plan_calefaccion_horario con sensores de Kaggle)
    st.caption(
        "ℹ️ Estimación basada en las horas PVPC más baratas del día. "
        "En el Bloque 3 incorporará la temperatura interior de la habitación (Kaggle)."
    )
    df_plan = df_day.copy()
    horas_baratas = set(df_plan.nsmallest(horas_base, "precio_eur_kwh")["hora"].tolist())
    df_plan["estado_disp"] = df_plan["hora"].apply(lambda h: "ON" if h in horas_baratas else "OFF")
    df_plan["color_semaforo"] = df_plan["estado_disp"].apply(lambda e: "VERDE" if e == "ON" else "ROJO")
    df_plan["consumo_estimado_kwh"] = df_plan["estado_disp"].apply(lambda e: potencia_kw if e == "ON" else 0.0)
    df_plan["coste_estimado_eur"] = (df_plan["consumo_estimado_kwh"] * df_plan["precio_eur_kwh"]).round(4)

# --- 1. Tabla inicial: Horas recomendadas de encendido ---
st.subheader(f"Horas recomendadas de encendido · {dev_info['nombre_dispositivo']}")
df_on = df_plan[df_plan["estado_disp"] == "ON"].copy()

tabla_resumen = pd.DataFrame(
    {
        "Hora": df_on["hora_label"],
        "Tramo PVPC": df_on["tramo_pvpc"],
        "Semáforo": df_on["color_semaforo"].apply(
            lambda c: "🟢 ON (VERDE)" if c == "VERDE" else "🔴 OFF (ROJO)"
        ),
        "Precio (€/kWh)": df_on["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
        "Coste hora (€)": df_on["coste_estimado_eur"].map(lambda x: f"{x:.4f} €"),
    }
)
st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

# --- 2. Tarjetas KPI del día ---
k1, k2, k3, k4 = st.columns(4)
k1.metric("Coste estimado día", f"{df_plan['coste_estimado_eur'].sum():.2f} €")
k2.metric("Consumo estimado", f"{df_plan['consumo_estimado_kwh'].sum():.2f} kWh")
k3.metric("Horas ON", f"{int((df_plan['estado_disp'] == 'ON').sum())} h")
k4.metric("Temp. media ext.", f"{df_plan['temperatura_ext_c'].mean():.1f} °C")

# --- 2b. Tarjetas KPI mensuales acumuladas (MTD) — solo para el termo por ahora ---
if tipo_disp == "termo":
    row_mes = df_mes[df_mes["fecha"] == fecha_sel]
    if not row_mes.empty:
        m = row_mes.iloc[0]
        st.subheader(f"Resumen mensual ({m['anio_mes']}) · {m['estado_mes']}")
        m1, m2, m3, m4 = st.columns(4)

        titulo_coste = (
            "Gasto total del mes"
            if m["es_mes_completo"]
            else f"Acumulado ({int(m['dias_acumulados'])}/{int(m['dias_totales_mes'])} días)"
        )
        m1.metric(titulo_coste, f"{m['coste_mes_eur']:.2f} €")
        m2.metric("Consumo acumulado", f"{m['consumo_mes_kwh']:.1f} kWh")
        m3.metric("Horas ON acumuladas", f"{int(m['total_horas_on_mes'])} h")
        m4.metric(
            "Proyección fin de mes" if not m["es_mes_completo"] else "Precio medio mes",
            f"{m['coste_proyectado_mes_eur']:.2f} €"
            if not m["es_mes_completo"]
            else f"{m['precio_medio_mes_eur_kwh']:.4f} €/kWh",
        )

st.divider()

# --- 3. Gráfico combinado 24h: Precio PVPC (semáforo) + Temperatura exterior ---
st.subheader("Planificación 24h: Precio PVPC vs. Temperatura exterior")
base = alt.Chart(df_plan).encode(
    x=alt.X("hora_label:O", title="Hora", axis=alt.Axis(labelAngle=0))
)

bars = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
    y=alt.Y("precio_eur_kwh:Q", title="Precio (€/kWh)"),
    color=alt.Color(
        "color_semaforo:N",
        scale=alt.Scale(domain=["VERDE", "ROJO"], range=["#2E7D32", "#C62828"]),
        legend=alt.Legend(title="Semáforo"),
    ),
    tooltip=[
        alt.Tooltip("hora_label:O", title="Hora"),
        alt.Tooltip("estado_disp:N", title="Estado"),
        alt.Tooltip("tramo_pvpc:N", title="Tramo PVPC"),
        alt.Tooltip("bloque_dia:N", title="Bloque"),
        alt.Tooltip("precio_eur_kwh:Q", title="Precio (€/kWh)", format=".4f"),
        alt.Tooltip("coste_estimado_eur:Q", title="Coste (€)", format=".4f"),
        alt.Tooltip("temperatura_ext_c:Q", title="Temp ext. (°C)", format=".1f"),
    ],
)

line = base.mark_line(color="#1565C0", strokeWidth=2.5, point=True).encode(
    y=alt.Y("temperatura_ext_c:Q", title="Temperatura (°C)"),
)

chart = (
    alt.layer(bars, line)
    .resolve_scale(y="independent")
    .properties(height=360)
)
st.altair_chart(chart, use_container_width=True)

# --- 4. Detalle completo 24h (desplegable) ---
with st.expander("Ver detalle completo de las 24 horas"):
    detalle = df_plan[
        [
            "hora_label",
            "bloque_dia",
            "tramo_pvpc",
            "estado_disp",
            "precio_eur_kwh",
            "temperatura_ext_c",
            "consumo_estimado_kwh",
            "coste_estimado_eur",
        ]
    ].rename(
        columns={
            "hora_label": "Hora",
            "bloque_dia": "Bloque",
            "tramo_pvpc": "Tramo PVPC",
            "estado_disp": "Estado",
            "precio_eur_kwh": "Precio (€/kWh)",
            "temperatura_ext_c": "Temp ext. (°C)",
            "consumo_estimado_kwh": "Consumo (kWh)",
            "coste_estimado_eur": "Coste (€)",
        }
    )
    st.dataframe(detalle, use_container_width=True, hide_index=True)