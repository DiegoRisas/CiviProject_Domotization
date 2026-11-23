from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

# --- Configuración de página ---
st.set_page_config(
    page_title="Panel 24h · Termo Eléctrico",
    page_icon="🔥",
    layout="wide",
)

# Cambia a DOMO_PRO_GOLD_DB cuando despliegues a producción
SOURCE_VIEW = "DOMO_DEV_GOLD_DB.ENERGIA.MART_PANEL_TERMO_24H"
MONTHLY_VIEW = "DOMO_DEV_GOLD_DB.ENERGIA.MART_RESUMEN_MENSUAL_TERMO"

session = get_active_session()


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


df = load_data(SOURCE_VIEW)
df_mes = load_monthly(MONTHLY_VIEW)

if df.empty:
    st.warning(f"No hay datos en `{SOURCE_VIEW}`.")
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

# --- Cabecera y selector de día ---
col_title, col_selector = st.columns([3, 1])
with col_title:
    st.title("🔥 Panel 24h · Termo Eléctrico")
    st.caption(aviso_auto)

with col_selector:
    fecha_sel = st.selectbox(
        "Seleccionar día",
        options=fechas_disponibles,
        index=default_index,
        format_func=lambda d: d.strftime("%d/%m/%Y"),
    )
    if st.button("🔄 Recargar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

df_day = df[df["fecha"] == fecha_sel].sort_values("hora").copy()
df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

# --- 1. Tabla inicial: 4 horas recomendadas (Hora, Semáforo, Precio) ---
st.subheader("Horas recomendadas de encendido")

df_top4 = df_day[df_day["estado_termo"] == "ON"].head(4).copy()
if df_top4.empty:
    df_top4 = df_day.nsmallest(4, "precio_eur_kwh").sort_values("hora").copy()

tabla_resumen = pd.DataFrame(
    {
        "Hora": df_top4["hora_label"],
        "Semáforo": df_top4["color_semaforo"].apply(
            lambda c: "🟢 ON (VERDE)" if c == "VERDE" else "🔴 OFF (ROJO)"
        ),
        "Precio (€/kWh)": df_top4["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
    }
)

st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

# --- 2. Tarjetas KPI del día ---
k1, k2, k3, k4 = st.columns(4)
k1.metric("Coste estimado día", f"{df_day['coste_estimado_eur'].sum():.2f} €")
k2.metric("Consumo estimado", f"{df_day['consumo_estimado_kwh'].sum():.2f} kWh")
k3.metric("Horas ON", f"{int((df_day['estado_termo'] == 'ON').sum())} h")
k4.metric("Temp. media ext.", f"{df_day['temperatura_ext_c'].mean():.1f} °C")

# --- 2b. Tarjetas KPI mensuales acumuladas hasta el día seleccionado (MTD) ---
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

base = alt.Chart(df_day).encode(
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
        alt.Tooltip("estado_termo:N", title="Estado"),
        alt.Tooltip("tramo_pvpc:N", title="Tramo PVPC"),
        alt.Tooltip("bloque_dia:N", title="Bloque"),
        alt.Tooltip("precio_eur_kwh:Q", title="Precio (€/kWh)", format=".4f"),
        alt.Tooltip("temperatura_ext_c:Q", title="Temp (°C)", format=".1f"),
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
    detalle = df_day[
        [
            "hora_label",
            "bloque_dia",
            "tramo_pvpc",
            "estado_termo",
            "precio_eur_kwh",
            "temperatura_ext_c",
            "coste_estimado_eur",
        ]
    ].rename(
        columns={
            "hora_label": "Hora",
            "bloque_dia": "Bloque",
            "tramo_pvpc": "Tramo PVPC",
            "estado_termo": "Estado",
            "precio_eur_kwh": "Precio (€/kWh)",
            "temperatura_ext_c": "Temp (°C)",
            "coste_estimado_eur": "Coste (€)",
        }
    )
    st.dataframe(detalle, use_container_width=True, hide_index=True)