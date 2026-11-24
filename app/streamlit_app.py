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
GOLD_DB = "DOMO_DEV_GOLD_DB"
DEVICES_TABLE = f"{GOLD_DB}.CORE.DIM_DISPOSITIVOS"
TERMO_VIEW = f"{GOLD_DB}.ENERGIA.MART_PANEL_TERMO_24H"
TERMO_MONTHLY_VIEW = f"{GOLD_DB}.ENERGIA.MART_RESUMEN_MENSUAL_TERMO"
PLANNER_VIEW = f"{GOLD_DB}.ENERGIA.MART_PLANIFICADOR_DISPOSITIVOS_24H"

session = get_active_session()


@st.cache_data(ttl=300)
def load_devices(table_name: str) -> pd.DataFrame:
    df_d = session.sql(f"SELECT * FROM {table_name} ORDER BY DISPOSITIVO_ID").to_pandas()
    df_d.columns = [c.lower() for c in df_d.columns]
    return df_d


@st.cache_data(ttl=300)
def load_termo(view_name: str) -> pd.DataFrame:
    df = session.sql(f"SELECT * FROM {view_name} ORDER BY FECHA, HORA").to_pandas()
    df.columns = [c.lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    return df


@st.cache_data(ttl=300)
def load_termo_monthly(view_name: str) -> pd.DataFrame:
    df_m = session.sql(f"SELECT * FROM {view_name} ORDER BY FECHA DESC").to_pandas()
    df_m.columns = [c.lower() for c in df_m.columns]
    df_m["fecha"] = pd.to_datetime(df_m["fecha"]).dt.date
    return df_m


@st.cache_data(ttl=300)
def load_planner(view_name: str) -> pd.DataFrame:
    df_p = session.sql(
        f"SELECT * FROM {view_name} ORDER BY FECHA, DISPOSITIVO_ID, HORA"
    ).to_pandas()
    df_p.columns = [c.lower() for c in df_p.columns]
    df_p["fecha"] = pd.to_datetime(df_p["fecha"]).dt.date
    return df_p


df_devices = load_devices(DEVICES_TABLE)
df_termo = load_termo(TERMO_VIEW)
df_termo_mes = load_termo_monthly(TERMO_MONTHLY_VIEW)
df_planner = load_planner(PLANNER_VIEW)

if df_devices.empty or df_termo.empty:
    st.warning(f"Faltan datos en `{DEVICES_TABLE}` o `{TERMO_VIEW}`.")
    st.stop()

# --- Regla de las 21:00 (Europe/Madrid) ---
now_madrid = datetime.now(ZoneInfo("Europe/Madrid"))
default_date = (
    (now_madrid + timedelta(days=1)).date()
    if now_madrid.hour >= 21
    else now_madrid.date()
)

fechas_disponibles = sorted(df_termo["fecha"].unique(), reverse=True)
if default_date in fechas_disponibles:
    default_index = fechas_disponibles.index(default_date)
    aviso_auto = (
        f"Auto ({now_madrid.strftime('%H:%M')}): "
        f"{'mostrando mañana (≥ 21:00)' if now_madrid.hour >= 21 else 'mostrando hoy (< 21:00)'}"
    )
else:
    default_index = 0
    aviso_auto = (
        f"Fecha objetivo ({default_date}) aún no disponible; mostrando último día cargado."
    )

# --- Cabecera y selectores globales (Dispositivo + Día + Recargar) ---
col_title, col_dev, col_date, col_btn = st.columns([2.5, 1.5, 1.1, 0.7])

with col_title:
    st.title("⚡ Panel 24h · Domótica y Energía")
    st.caption(aviso_auto)

with col_dev:
    dispositivos_ids = df_devices["dispositivo_id"].tolist()
    labels_disp = {
        row["dispositivo_id"]: f"{row['nombre_dispositivo']} ({row['nombre_habitacion']})"
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
    if st.button("🔄 Recargar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Ficha técnica rápida desde DIM_DISPOSITIVOS
dev_info = df_devices[df_devices["dispositivo_id"] == disp_sel].iloc[0]
tipo_disp = str(dev_info["tipo_dispositivo"])
nombre_disp = str(dev_info["nombre_dispositivo"])
nombre_hab = str(dev_info["nombre_habitacion"])
potencia_kw = float(dev_info["potencia_nominal_kw"])
horas_base = int(dev_info["horas_base_dia"])

st.info(
    f"📍 Estancia: **{nombre_hab}** · Tipo: `{tipo_disp}` · "
    f"Potencia: **{potencia_kw:.2f} kW** · Referencia base: **{horas_base} h/día**"
)


# ==============================================================================
# MODO 1 · TERMO ELÉCTRICO (INMUTABLE · SIN SLIDER · CON MTD MENSUAL)
# ==============================================================================
if tipo_disp == "termo":
    df_day = df_termo[df_termo["fecha"] == fecha_sel].sort_values("hora").copy()
    if df_day.empty:
        st.warning(f"No hay datos del termo para el día {fecha_sel}.")
        st.stop()

    df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

    # 1. Tabla de horas recomendadas
    st.subheader(f"Horas recomendadas de encendido · {nombre_disp}")
    df_on = df_day[df_day["estado_termo"] == "ON"].copy()

    tabla_resumen = pd.DataFrame(
        {
            "Hora": df_on["hora_label"],
            "Bloque": df_on["bloque_dia"],
            "Tramo PVPC": df_on["tramo_pvpc"],
            "Semáforo": df_on["color_semaforo"].apply(
                lambda c: "🟢 ON (VERDE)" if c == "VERDE" else "🔴 OFF (ROJO)"
            ),
            "Precio (€/kWh)": df_on["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
            "Coste hora (€)": df_on["coste_estimado_eur"].map(lambda x: f"{x:.4f} €"),
        }
    )
    st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

    # 2. KPIs diarios
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Coste estimado día", f"{df_day['coste_estimado_eur'].sum():.2f} €")
    k2.metric("Consumo estimado", f"{df_day['consumo_estimado_kwh'].sum():.2f} kWh")
    k3.metric("Horas ON", f"{int((df_day['estado_termo'] == 'ON').sum())} h")
    k4.metric("Temp. media ext.", f"{df_day['temperatura_ext_c'].mean():.1f} °C")

    # 2b. KPIs mensuales acumulados (MTD)
    row_mes = df_termo_mes[df_termo_mes["fecha"] == fecha_sel]
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

    # 3. Gráfico 24h: PVPC (semáforo) + Temperatura exterior
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
            alt.Tooltip("coste_estimado_eur:Q", title="Coste (€)", format=".4f"),
            alt.Tooltip("temperatura_ext_c:Q", title="Temp. ext. (°C)", format=".1f"),
        ],
    )
    line = base.mark_line(color="#1565C0", strokeWidth=2.5, point=True).encode(
        y=alt.Y("temperatura_ext_c:Q", title="Temperatura ext. (°C)"),
    )
    chart = (
        alt.layer(bars, line)
        .resolve_scale(y="independent")
        .properties(height=360)
    )
    st.altair_chart(chart, use_container_width=True)

    # 4. Detalle completo 24h
    with st.expander("Ver detalle completo de las 24 horas"):
        detalle = df_day[
            [
                "hora_label",
                "bloque_dia",
                "tramo_pvpc",
                "estado_termo",
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
                "estado_termo": "Estado",
                "precio_eur_kwh": "Precio (€/kWh)",
                "temperatura_ext_c": "Temp. ext. (°C)",
                "consumo_estimado_kwh": "Consumo (kWh)",
                "coste_estimado_eur": "Coste (€)",
            }
        )
        st.dataframe(detalle, use_container_width=True, hide_index=True)


# ==============================================================================
# MODO 2 · CALEFACTOR PORTÁTIL (SLIDER 0–24h + CONFORT TÉRMICO INTERIOR)
# ==============================================================================
elif tipo_disp == "calefactor_portatil":
    df_day = df_planner[
        (df_planner["fecha"] == fecha_sel) & (df_planner["dispositivo_id"] == disp_sel)
    ].sort_values("hora").copy()

    if df_day.empty:
        st.warning(
            f"No hay datos en `{PLANNER_VIEW}` para {nombre_disp} el día {fecha_sel}."
        )
        st.stop()

    df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

    horas_min_rec = int(df_day["horas_minimas_recomendadas_dia"].iloc[0])
    temp_confort_min = float(df_day["temp_confort_min_c"].iloc[0])
    horas_con_frio = int(df_day["necesita_calor"].sum())

    # Aviso de recomendación mínima para confort + Slider 0–24h
    col_aviso, col_slider = st.columns([1.6, 1.4])
    with col_aviso:
        if horas_min_rec > 0:
            st.success(
                f"🌡️ **Recomendación mínima para confort ({temp_confort_min:.1f} °C):** "
                f"enchufar al menos **{horas_min_rec} h** "
                f"({horas_con_frio} h del día por debajo de confort)."
            )
        else:
            st.success(
                f"🌡️ **Estancia en confort ({temp_confort_min:.1f} °C):** "
                "no hace frío en ninguna hora del día (mínimo recomendado: **0 h**)."
            )

    with col_slider:
        horas_sel = st.slider(
            "¿Cuántas horas quieres encender el calefactor hoy?",
            min_value=0,
            max_value=24,
            value=horas_min_rec,
            key=f"slider_{disp_sel}_{fecha_sel}",
        )

    # Aplicar selección del slider sobre ranking_prioridad_dia precalculado en Gold
    df_day["estado_sel"] = df_day["ranking_prioridad_dia"].apply(
        lambda r: "ON" if r <= horas_sel else "OFF"
    )
    df_day["color_semaforo"] = df_day["estado_sel"].apply(
        lambda e: "VERDE" if e == "ON" else "ROJO"
    )
    df_day["consumo_sel_kwh"] = df_day.apply(
        lambda r: r["consumo_si_on_kwh"] if r["estado_sel"] == "ON" else 0.0, axis=1
    )
    df_day["coste_sel_eur"] = df_day.apply(
        lambda r: r["coste_si_on_eur"] if r["estado_sel"] == "ON" else 0.0, axis=1
    )

    # 1. Tabla de horas ON según el slider
    st.subheader(f"Horas recomendadas de encendido ({horas_sel} h) · {nombre_disp}")
    df_on = df_day[df_day["estado_sel"] == "ON"].sort_values("hora").copy()

    if df_on.empty:
        st.info("Con 0 horas seleccionadas, el calefactor permanecerá apagado todo el día.")
    else:
        tabla_resumen = pd.DataFrame(
            {
                "Hora": df_on["hora_label"],
                "Prioridad": df_on["ranking_prioridad_dia"].map(lambda r: f"#{int(r)}"),
                "Tramo PVPC": df_on["tramo_pvpc"],
                "Temp. interior (°C)": df_on["temp_interior_c"].map(
                    lambda x: f"{x:.1f} °C" if pd.notna(x) else "—"
                ),
                "Déficit (°C)": df_on["deficit_termico_c"].map(lambda x: f"{x:.1f} °C"),
                "Precio (€/kWh)": df_on["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
                "Coste hora (€)": df_on["coste_sel_eur"].map(lambda x: f"{x:.4f} €"),
            }
        )
        st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

    # 2. KPIs dinámicos según el slider
    temp_int_media = df_day["temp_interior_c"].mean()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Coste estimado día", f"{df_day['coste_sel_eur'].sum():.2f} €")
    k2.metric("Consumo estimado", f"{df_day['consumo_sel_kwh'].sum():.2f} kWh")
    k3.metric("Horas ON (mín. rec.)", f"{horas_sel} h", delta=f"Mín: {horas_min_rec} h", delta_color="off")
    k4.metric(
        "Temp. media interior",
        f"{temp_int_media:.1f} °C" if pd.notna(temp_int_media) else "Sin sensor",
    )

    st.divider()

    # 3. Gráfico 24h: Barras PVPC (Verde/Rojo) + Curva Temp. interior + Línea confort mínima
    st.subheader(
        f"Planificación 24h: Precio PVPC vs. Temp. interior ({nombre_hab}) y Confort ({temp_confort_min:.1f} °C)"
    )
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
            alt.Tooltip("estado_sel:N", title="Estado"),
            alt.Tooltip("ranking_prioridad_dia:Q", title="Prioridad"),
            alt.Tooltip("tramo_pvpc:N", title="Tramo PVPC"),
            alt.Tooltip("precio_eur_kwh:Q", title="Precio (€/kWh)", format=".4f"),
            alt.Tooltip("coste_sel_eur:Q", title="Coste (€)", format=".4f"),
            alt.Tooltip("temp_interior_c:Q", title="Temp. interior (°C)", format=".1f"),
            alt.Tooltip("temp_confort_min_c:Q", title="Confort mín. (°C)", format=".1f"),
        ],
    )

    line_temp_int = base.mark_line(color="#1565C0", strokeWidth=2.5, point=True).encode(
        y=alt.Y("temp_interior_c:Q", title="Temperatura interior (°C)"),
    )

    rule_confort = base.mark_rule(
        color="#EF6C00", strokeDash=[6, 4], strokeWidth=2
    ).encode(
        y=alt.Y("temp_confort_min_c:Q"),
    )

    temp_layer = alt.layer(line_temp_int, rule_confort)

    chart = (
        alt.layer(bars, temp_layer)
        .resolve_scale(y="independent")
        .properties(height=380)
    )
    st.altair_chart(chart, use_container_width=True)

    # 4. Detalle completo 24h
    with st.expander("Ver detalle completo de las 24 horas"):
        detalle = df_day[
            [
                "hora_label",
                "tramo_pvpc",
                "ranking_prioridad_dia",
                "estado_sel",
                "temp_interior_c",
                "temp_confort_min_c",
                "deficit_termico_c",
                "precio_eur_kwh",
                "consumo_sel_kwh",
                "coste_sel_eur",
            ]
        ].rename(
            columns={
                "hora_label": "Hora",
                "tramo_pvpc": "Tramo PVPC",
                "ranking_prioridad_dia": "Prioridad",
                "estado_sel": "Estado",
                "temp_interior_c": "Temp. int. (°C)",
                "temp_confort_min_c": "Confort mín. (°C)",
                "deficit_termico_c": "Déficit (°C)",
                "precio_eur_kwh": "Precio (€/kWh)",
                "consumo_sel_kwh": "Consumo (kWh)",
                "coste_sel_eur": "Coste (€)",
            }
        )
        st.dataframe(detalle, use_container_width=True, hide_index=True)


# ==============================================================================
# MODO 3 · ELECTRODOMÉSTICO (SLIDER 1–6h · BLOQUE CONSECUTIVO MÁS BARATO)
# ==============================================================================
else:
    df_day = (
        df_planner[
            (df_planner["fecha"] == fecha_sel)
            & (df_planner["dispositivo_id"] == disp_sel)
        ]
        .sort_values("hora")
        .reset_index(drop=True)
        .copy()
    )

    if df_day.empty:
        st.warning(
            f"No hay datos en `{PLANNER_VIEW}` para {nombre_disp} el día {fecha_sel}."
        )
        st.stop()

    df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

    default_ciclo = min(6, max(1, int(df_day["horas_minimas_recomendadas_dia"].iloc[0])))
    horas_sel = st.slider(
        f"Duración del ciclo de {nombre_disp} (horas consecutivas)",
        min_value=1,
        max_value=6,
        value=default_ciclo,
        key=f"slider_{disp_sel}_{fecha_sel}",
    )

    # Ventana móvil de `horas_sel` horas consecutivas con menor suma de precio PVPC
    ventana_precio = df_day["precio_eur_kwh"].rolling(window=horas_sel).sum()
    idx_fin = int(ventana_precio.idxmin())
    idx_inicio = idx_fin - horas_sel + 1

    hora_inicio = int(df_day.loc[idx_inicio, "hora"])
    hora_fin = int(df_day.loc[idx_fin, "hora"]) + 1

    df_day["estado_sel"] = "OFF"
    df_day.loc[idx_inicio:idx_fin, "estado_sel"] = "ON"
    df_day["color_semaforo"] = df_day["estado_sel"].apply(
        lambda e: "VERDE" if e == "ON" else "ROJO"
    )
    df_day["consumo_sel_kwh"] = df_day.apply(
        lambda r: r["consumo_si_on_kwh"] if r["estado_sel"] == "ON" else 0.0, axis=1
    )
    df_day["coste_sel_eur"] = df_day.apply(
        lambda r: r["coste_si_on_eur"] if r["estado_sel"] == "ON" else 0.0, axis=1
    )

    coste_ciclo = df_day["coste_sel_eur"].sum()
    st.success(
        f"🫧 **Mejor franja consecutiva ({horas_sel} h):** "
        f"programar de **{hora_inicio:02d}:00** a **{hora_fin:02d}:00** "
        f"(coste estimado del ciclo: **{coste_ciclo:.2f} €**)."
    )

    # 1. Tabla del bloque consecutivo recomendado
    st.subheader(f"Ciclo recomendado ({hora_inicio:02d}:00 – {hora_fin:02d}:00) · {nombre_disp}")
    df_on = df_day[df_day["estado_sel"] == "ON"].sort_values("hora").copy()

    tabla_resumen = pd.DataFrame(
        {
            "Hora": df_on["hora_label"],
            "Tramo PVPC": df_on["tramo_pvpc"],
            "Semáforo": "🟢 ON (VERDE)",
            "Precio (€/kWh)": df_on["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
            "Coste hora (€)": df_on["coste_sel_eur"].map(lambda x: f"{x:.4f} €"),
        }
    )
    st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

    # 2. KPIs del ciclo
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Coste estimado ciclo", f"{coste_ciclo:.2f} €")
    k2.metric("Consumo ciclo", f"{df_day['consumo_sel_kwh'].sum():.2f} kWh")
    k3.metric("Franja óptima", f"{hora_inicio:02d}:00 – {hora_fin:02d}:00")
    k4.metric("Precio medio ciclo", f"{df_on['precio_eur_kwh'].mean():.4f} €/kWh")

    st.divider()

    # 3. Gráfico 24h PVPC (Verde/Rojo)
    st.subheader(f"Planificación 24h: Precio PVPC ({nombre_disp})")
    chart = (
        alt.Chart(df_day)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("hora_label:O", title="Hora", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("precio_eur_kwh:Q", title="Precio (€/kWh)"),
            color=alt.Color(
                "color_semaforo:N",
                scale=alt.Scale(domain=["VERDE", "ROJO"], range=["#2E7D32", "#C62828"]),
                legend=alt.Legend(title="Semáforo"),
            ),
            tooltip=[
                alt.Tooltip("hora_label:O", title="Hora"),
                alt.Tooltip("estado_sel:N", title="Estado"),
                alt.Tooltip("tramo_pvpc:N", title="Tramo PVPC"),
                alt.Tooltip("precio_eur_kwh:Q", title="Precio (€/kWh)", format=".4f"),
                alt.Tooltip("coste_sel_eur:Q", title="Coste (€)", format=".4f"),
            ],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, use_container_width=True)

    # 4. Detalle completo 24h
    with st.expander("Ver detalle completo de las 24 horas"):
        detalle = df_day[
            [
                "hora_label",
                "tramo_pvpc",
                "estado_sel",
                "precio_eur_kwh",
                "consumo_sel_kwh",
                "coste_sel_eur",
            ]
        ].rename(
            columns={
                "hora_label": "Hora",
                "tramo_pvpc": "Tramo PVPC",
                "estado_sel": "Estado",
                "precio_eur_kwh": "Precio (€/kWh)",
                "consumo_sel_kwh": "Consumo (kWh)",
                "coste_sel_eur": "Coste (€)",
            }
        )
        st.dataframe(detalle, use_container_width=True, hide_index=True)