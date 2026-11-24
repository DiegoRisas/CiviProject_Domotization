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
# MODO 1 · TERMO ELÉCTRICO (PLAN OFICIAL GOLD + SIMULADOR DE CAPACIDAD, POTENCIA Y HORAS)
# ==============================================================================
def simular_horas_termo_df(df_in: pd.DataFrame, horas_objetivo: int, pot_kw: float) -> pd.DataFrame:
    """Aplica el reparto por bloque_dia (Madrugada -> Mediodia -> Tarde_Noche) y potencia en kW."""
    base_b = horas_objetivo // 3
    resto_b = horas_objetivo % 3
    cuotas_bloque = {
        "Madrugada": base_b + (1 if resto_b >= 1 else 0),
        "Mediodia": base_b + (1 if resto_b >= 2 else 0),
        "Tarde_Noche": base_b,
    }

    df_out = df_in.sort_values(["fecha", "bloque_dia", "precio_eur_kwh", "hora"]).copy()
    df_out["rank_bloque"] = df_out.groupby(["fecha", "bloque_dia"]).cumcount() + 1
    df_out["cuota_bloque"] = df_out["bloque_dia"].map(cuotas_bloque).fillna(0)

    df_out["estado_plan"] = (df_out["rank_bloque"] <= df_out["cuota_bloque"]).map(
        {True: "ON", False: "OFF"}
    )
    df_out["semaforo_plan"] = df_out["estado_plan"].map({"ON": "VERDE", "OFF": "ROJO"})
    df_out["consumo_plan_kwh"] = df_out["estado_plan"].map({"ON": pot_kw, "OFF": 0.0})
    df_out["coste_plan_eur"] = (df_out["consumo_plan_kwh"] * df_out["precio_eur_kwh"]).round(4)

    return df_out.sort_values(["fecha", "hora"]).drop(columns=["rank_bloque", "cuota_bloque"])


if tipo_disp == "termo":
    df_day_oficial = df_termo[df_termo["fecha"] == fecha_sel].sort_values("hora").copy()
    if df_day_oficial.empty:
        st.warning(f"No hay datos del termo para el día {fecha_sel}.")
        st.stop()

    # Valores por defecto desde DIM_DISPOSITIVOS (seed: 100 L y 1200 W)
    litros_seed = (
        int(dev_info["capacidad_litros"])
        if pd.notna(dev_info.get("capacidad_litros"))
        else 100
    )
    watts_seed = int(round(potencia_kw * 1000)) if potencia_kw > 0 else 1200

    # Métricas base del plan oficial inmutable de Gold
    horas_oficial = int((df_day_oficial["estado_termo"] == "ON").sum())
    coste_oficial = float(df_day_oficial["coste_estimado_eur"].sum())
    consumo_oficial = float(df_day_oficial["consumo_estimado_kwh"].sum())

    # --- Panel de personalización del termo (Litros, Watts y Simulador de horas) ---
    col_lit, col_watts, col_tog, col_sld = st.columns([1.0, 1.0, 1.1, 1.5])

    with col_lit:
        litros_input = st.number_input(
            "Capacidad termo (litros)",
            min_value=15,
            max_value=500,
            value=litros_seed,
            step=10,
            key=f"litros_termo_{disp_sel}",
        )

    with col_watts:
        watts_input = st.number_input(
            "Potencia resistencia (W)",
            min_value=500,
            max_value=6000,
            value=watts_seed,
            step=100,
            key=f"watts_termo_{disp_sel}",
        )

    potencia_sim_kw = watts_input / 1000.0
    # Estimación física de horas necesarias para calentar el depósito completo desde ~15 °C a ~55 °C
    horas_orientativas_litros = max(1, round((litros_input * 0.0465) / potencia_sim_kw))

    with col_tog:
        st.write("")
        simular_termo = st.toggle(
            "Simular otras horas",
            value=False,
            key=f"toggle_termo_{fecha_sel}",
        )

    with col_sld:
        if simular_termo:
            horas_sim = st.slider(
                "Horas encendido/día",
                min_value=1,
                max_value=12,
                value=max(1, min(12, horas_orientativas_litros)),
                key=f"slider_termo_{fecha_sel}",
            )
        else:
            horas_sim = horas_oficial
            st.caption(
                f"💡 Para **{litros_input} L** a **{watts_input} W**, calentar el depósito completo "
                f"requiere ~**{horas_orientativas_litros} h**."
            )

    termo_personalizado = (
        simular_termo or (watts_input != watts_seed) or (litros_input != litros_seed)
    )

    if termo_personalizado:
        # Si no activó el toggle de horas, mantiene las horas oficiales de Gold con la nueva potencia
        horas_objetivo_calc = horas_sim if simular_termo else horas_oficial
        df_day = simular_horas_termo_df(df_day_oficial, horas_objetivo_calc, potencia_sim_kw)

        coste_sim = float(df_day["coste_plan_eur"].sum())
        diff_dia = coste_sim - coste_oficial
        diff_30d = diff_dia * 30

        base_b = horas_objetivo_calc // 3
        resto_b = horas_objetivo_calc % 3
        cuotas = {
            "Madrugada": base_b + (1 if resto_b >= 1 else 0),
            "Mediodia": base_b + (1 if resto_b >= 2 else 0),
            "Tarde_Noche": base_b,
        }
        bloques_sin_cobertura = [b.replace("_", "/") for b, n in cuotas.items() if n == 0]
        aviso_cobertura = (
            f", pero pierdes cobertura en **{' y '.join(bloques_sin_cobertura)}**"
            if bloques_sin_cobertura
            else " manteniendo cobertura en los 3 bloques del día"
        )

        resumen_config = f"{litros_input} L · {watts_input} W · {horas_objetivo_calc} h/día"
        if abs(diff_dia) < 0.005:
            st.info(
                f"⚖️ **Termo personalizado ({resumen_config}):** mismo coste diario que el plan base "
                f"(**{coste_sim:.2f} €/día**){aviso_cobertura}."
            )
        elif diff_dia < 0:
            st.success(
                f"💰 **Termo personalizado ({resumen_config} vs. {litros_seed} L · {watts_seed} W · {horas_oficial} h):** "
                f"ahorras **{abs(diff_dia):.2f} €/día** (~**{abs(diff_30d):.2f} €/mes**)"
                f"{aviso_cobertura}."
            )
        else:
            st.warning(
                f"📈 **Termo personalizado ({resumen_config} vs. {litros_seed} L · {watts_seed} W · {horas_oficial} h):** "
                f"supone **+{diff_dia:.2f} €/día** (~**+{diff_30d:.2f} €/mes**){aviso_cobertura}."
            )
    else:
        horas_objetivo_calc = horas_oficial
        df_day = df_day_oficial.copy()
        df_day["estado_plan"] = df_day["estado_termo"]
        df_day["semaforo_plan"] = df_day["color_semaforo"]
        df_day["consumo_plan_kwh"] = df_day["consumo_estimado_kwh"]
        df_day["coste_plan_eur"] = df_day["coste_estimado_eur"]

    df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

    # 1. Tabla de horas recomendadas / simuladas
    etiqueta_modo = "simuladas" if termo_personalizado else "recomendadas"
    st.subheader(
        f"Horas {etiqueta_modo} de encendido · {nombre_disp} ({litros_input} L · {watts_input} W)"
    )
    df_on = df_day[df_day["estado_plan"] == "ON"].copy()

    tabla_resumen = pd.DataFrame(
        {
            "Hora": df_on["hora_label"],
            "Bloque": df_on["bloque_dia"],
            "Tramo PVPC": df_on["tramo_pvpc"],
            "Semáforo": df_on["semaforo_plan"].apply(
                lambda c: "🟢 ON (VERDE)" if c == "VERDE" else "🔴 OFF (ROJO)"
            ),
            "Precio (€/kWh)": df_on["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
            "Coste hora (€)": df_on["coste_plan_eur"].map(lambda x: f"{x:.4f} €"),
        }
    )
    st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

    # 2. KPIs diarios
    coste_actual = float(df_day["coste_plan_eur"].sum())
    consumo_actual = float(df_day["consumo_plan_kwh"].sum())
    horas_actual = int((df_day["estado_plan"] == "ON").sum())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Coste estimado día",
        f"{coste_actual:.2f} €",
        delta=f"{coste_actual - coste_oficial:+.2f} € vs base" if termo_personalizado else None,
        delta_color="inverse",
    )
    k2.metric(
        "Consumo estimado",
        f"{consumo_actual:.2f} kWh",
        delta=f"{consumo_actual - consumo_oficial:+.2f} kWh" if termo_personalizado else None,
        delta_color="off",
    )
    k3.metric(
        "Horas ON",
        f"{horas_actual} h",
        delta=f"{horas_actual - horas_oficial:+d} h vs base" if simular_termo else None,
        delta_color="off",
    )
    k4.metric("Temp. media ext.", f"{df_day['temperatura_ext_c'].mean():.1f} °C")

    # 2b. KPIs mensuales acumulados hasta fecha_sel (MTD oficial o personalizado)
    row_mes = df_termo_mes[df_termo_mes["fecha"] == fecha_sel]
    if not row_mes.empty:
        m = row_mes.iloc[0]
        es_completo = bool(m["es_mes_completo"])
        dias_acum = int(m["dias_acumulados"])
        dias_tot = int(m["dias_totales_mes"])

        if termo_personalizado:
            inicio_mes = fecha_sel.replace(day=1)
            df_mtd_raw = df_termo[
                (df_termo["fecha"] >= inicio_mes) & (df_termo["fecha"] <= fecha_sel)
            ]
            # Si no se activó el toggle de horas, conserva exactamente las horas ON oficiales de cada día
            # (incluyendo la hora extra de días fríos) y aplica solo la nueva potencia en W
            if simular_termo:
                df_mtd_sim = simular_horas_termo_df(
                    df_mtd_raw, horas_objetivo_calc, potencia_sim_kw
                )
            else:
                df_mtd_sim = df_mtd_raw.copy()
                df_mtd_sim["estado_plan"] = df_mtd_sim["estado_termo"]
                df_mtd_sim["consumo_plan_kwh"] = df_mtd_sim["estado_plan"].map(
                    {"ON": potencia_sim_kw, "OFF": 0.0}
                )
                df_mtd_sim["coste_plan_eur"] = (
                    df_mtd_sim["consumo_plan_kwh"] * df_mtd_sim["precio_eur_kwh"]
                ).round(4)

            coste_mes_val = round(float(df_mtd_sim["coste_plan_eur"].sum()), 2)
            consumo_mes_val = round(float(df_mtd_sim["consumo_plan_kwh"].sum()), 1)
            horas_mes_val = int((df_mtd_sim["estado_plan"] == "ON").sum())
            proyeccion_mes_val = (
                coste_mes_val
                if es_completo
                else round((coste_mes_val / max(1, dias_acum)) * dias_tot, 2)
            )
            sufijo_titulo = f" · Simulación ({litros_input} L · {watts_input} W)"
        else:
            coste_mes_val = float(m["coste_mes_eur"])
            consumo_mes_val = float(m["consumo_mes_kwh"])
            horas_mes_val = int(m["total_horas_on_mes"])
            proyeccion_mes_val = float(m["coste_proyectado_mes_eur"])
            sufijo_titulo = ""

        st.subheader(f"Resumen mensual ({m['anio_mes']}) · {m['estado_mes']}{sufijo_titulo}")
        m1, m2, m3, m4 = st.columns(4)

        titulo_coste = (
            "Gasto total del mes"
            if es_completo
            else f"Acumulado ({dias_acum}/{dias_tot} días)"
        )
        m1.metric(
            titulo_coste,
            f"{coste_mes_val:.2f} €",
            delta=f"{coste_mes_val - float(m['coste_mes_eur']):+.2f} € vs base"
            if termo_personalizado
            else None,
            delta_color="inverse",
        )
        m2.metric(
            "Consumo acumulado",
            f"{consumo_mes_val:.1f} kWh",
            delta=f"{consumo_mes_val - float(m['consumo_mes_kwh']):+.1f} kWh"
            if termo_personalizado
            else None,
            delta_color="off",
        )
        m3.metric(
            "Horas ON acumuladas",
            f"{horas_mes_val} h",
            delta=f"{horas_mes_val - int(m['total_horas_on_mes']):+d} h vs base"
            if simular_termo
            else None,
            delta_color="off",
        )
        m4.metric(
            "Proyección fin de mes" if not es_completo else "Precio medio mes",
            f"{proyeccion_mes_val:.2f} €"
            if not es_completo
            else f"{m['precio_medio_mes_eur_kwh']:.4f} €/kWh",
            delta=(
                f"{proyeccion_mes_val - float(m['coste_proyectado_mes_eur']):+.2f} € vs base"
                if (termo_personalizado and not es_completo)
                else None
            ),
            delta_color="inverse",
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
            "semaforo_plan:N",
            scale=alt.Scale(domain=["VERDE", "ROJO"], range=["#2E7D32", "#C62828"]),
            legend=alt.Legend(title="Semáforo"),
        ),
        tooltip=[
            alt.Tooltip("hora_label:O", title="Hora"),
            alt.Tooltip("estado_plan:N", title="Estado"),
            alt.Tooltip("tramo_pvpc:N", title="Tramo PVPC"),
            alt.Tooltip("bloque_dia:N", title="Bloque"),
            alt.Tooltip("precio_eur_kwh:Q", title="Precio (€/kWh)", format=".4f"),
            alt.Tooltip("coste_plan_eur:Q", title="Coste (€)", format=".4f"),
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
                "estado_plan",
                "precio_eur_kwh",
                "temperatura_ext_c",
                "consumo_plan_kwh",
                "coste_plan_eur",
            ]
        ].rename(
            columns={
                "hora_label": "Hora",
                "bloque_dia": "Bloque",
                "tramo_pvpc": "Tramo PVPC",
                "estado_plan": "Estado",
                "precio_eur_kwh": "Precio (€/kWh)",
                "temperatura_ext_c": "Temp. ext. (°C)",
                "consumo_plan_kwh": "Consumo (kWh)",
                "coste_plan_eur": "Coste (€)",
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
# MODO 3 · ELECTRODOMÉSTICO (PLANIFICADOR MULTIUSOS: WATTS + HORAS Y MINUTOS)
# ==============================================================================
else:
    df_day = df_planner[
        (df_planner["fecha"] == fecha_sel) & (df_planner["dispositivo_id"] == disp_sel)
    ].sort_values("hora").copy()

    if df_day.empty:
        st.warning(
            f"No hay datos en `{PLANNER_VIEW}` para {nombre_disp} el día {fecha_sel}."
        )
        st.stop()

    df_day["hora_label"] = df_day["hora"].apply(lambda h: f"{int(h):02d}:00")

    # --- Perfiles rápidos de potencia ---
    perfiles_watts = {
        "🧼 Lavadora (2000 W)": 2000,
        "🍽️ Lavavajillas (1800 W)": 1800,
        "🔥 Horno (2200 W)": 2200,
        "🍟 Airfryer (1500 W)": 1500,
    }
    watts_key = f"watts_elec_{disp_sel}"
    if watts_key not in st.session_state:
        st.session_state[watts_key] = max(100, min(4000, int(round(potencia_kw * 1000))))

    if hasattr(st, "pills"):
        perfil_sel = st.pills(
            "Perfiles típicos (opcional)",
            options=list(perfiles_watts.keys()),
            key=f"pills_{disp_sel}",
        )
        if perfil_sel and st.session_state.get(f"last_pill_{disp_sel}") != perfil_sel:
            st.session_state[watts_key] = perfiles_watts[perfil_sel]
            st.session_state[f"last_pill_{disp_sel}"] = perfil_sel
    else:
        cols_presets = st.columns(len(perfiles_watts))
        for col_p, (label_p, val_w) in zip(cols_presets, perfiles_watts.items()):
            if col_p.button(label_p, use_container_width=True, key=f"btn_{disp_sel}_{val_w}"):
                st.session_state[watts_key] = val_w

    # --- 3 controles: Potencia (W) + Horas (0–6) + Minutos (0–59) ---
    default_ciclo = min(6, max(1, int(df_day["horas_minimas_recomendadas_dia"].iloc[0])))
    c_watts, c_horas, c_mins = st.columns([1.2, 1.0, 1.0])

    with c_watts:
        watts_sel = st.number_input(
            "Potencia del aparato (W)",
            min_value=100,
            max_value=4000,
            step=100,
            key=watts_key,
        )

    with c_horas:
        horas_ciclo = st.selectbox(
            "Duración · Horas",
            options=list(range(0, 7)),
            index=default_ciclo,
            key=f"horas_elec_{disp_sel}_{fecha_sel}",
        )

    with c_mins:
        minutos_ciclo = st.selectbox(
            "Duración · Minutos",
            options=list(range(0, 60)),
            index=0,
            key=f"mins_elec_{disp_sel}_{fecha_sel}",
        )

    total_minutos = horas_ciclo * 60 + minutos_ciclo
    if total_minutos <= 0:
        st.warning("⚠️ Selecciona una duración total mayor que 0 minutos.")
        st.stop()

    potencia_sim_kw = watts_sel / 1000.0
    duracion_horas_dec = total_minutos / 60.0
    texto_duracion = (
        f"{horas_ciclo} h {minutos_ciclo:02d} min"
        if horas_ciclo > 0 and minutos_ciclo > 0
        else (f"{horas_ciclo} h" if horas_ciclo > 0 else f"{minutos_ciclo} min")
    )

    # --- Cálculo de ventana consecutiva exacta (horas completas + fracción final) ---
    precios = df_day["precio_eur_kwh"].tolist()  # índice 0..23 = hora 00..23
    n_completas = horas_ciclo
    frac_ultima = minutos_ciclo / 60.0
    slots_totales = n_completas + (1 if frac_ultima > 0 else 0)

    mejor_h = 0
    mejor_coste = float("inf")

    for h in range(0, 24 - slots_totales + 1):
        suma_precio_equiv = sum(precios[h : h + n_completas])
        if frac_ultima > 0:
            suma_precio_equiv += frac_ultima * precios[h + n_completas]
        coste_h = potencia_sim_kw * suma_precio_equiv
        if coste_h < mejor_coste:
            mejor_coste = coste_h
            mejor_h = h

    # --- Comparativa: "Ponerlo ahora vs. programarlo" ---
    hora_ahora = now_madrid.hour
    suma_ahora_equiv = sum(precios[(hora_ahora + k) % 24] for k in range(n_completas))
    if frac_ultima > 0:
        suma_ahora_equiv += frac_ultima * precios[(hora_ahora + n_completas) % 24]
    coste_ahora = potencia_sim_kw * suma_ahora_equiv
    ahorro_diferido = coste_ahora - mejor_coste
    pct_ahorro = (ahorro_diferido / coste_ahora * 100) if coste_ahora > 0 else 0.0

    min_inicio_total = mejor_h * 60
    min_fin_total = min_inicio_total + total_minutos
    hora_fin_str = f"{(min_fin_total // 60) % 24:02d}:{min_fin_total % 60:02d}"
    franja_optima_str = f"{mejor_h:02d}:00 – {hora_fin_str}"

    if ahorro_diferido > 0.005:
        st.success(
            f"⏱️ **Programarlo ({franja_optima_str}) vs. ponerlo ahora ({hora_ahora:02d}:00):** "
            f"cuesta **{mejor_coste:.2f} €** frente a **{coste_ahora:.2f} €** ahora — "
            f"ahorras **{ahorro_diferido:.2f} €** (**{pct_ahorro:.0f}%** menos) usando inicio diferido."
        )
    else:
        st.info(
            f"⏱️ **¡Buen momento ahora ({hora_ahora:02d}:00)!** El coste actual (**{coste_ahora:.2f} €**) "
            f"coincide prácticamente con la mejor franja del día (**{franja_optima_str}**, **{mejor_coste:.2f} €**)."
        )

    # Marcar horas activas y fracción de uso por cada hora del día
    fraccion_por_hora = {h: 0.0 for h in range(24)}
    for k in range(n_completas):
        fraccion_por_hora[mejor_h + k] = 1.0
    if frac_ultima > 0:
        fraccion_por_hora[mejor_h + n_completas] = frac_ultima

    df_day["fraccion_uso"] = df_day["hora"].map(fraccion_por_hora)
    df_day["estado_sel"] = df_day["fraccion_uso"].apply(lambda f: "ON" if f > 0 else "OFF")
    df_day["color_semaforo"] = df_day["estado_sel"].apply(
        lambda e: "VERDE" if e == "ON" else "ROJO"
    )
    df_day["consumo_sel_kwh"] = (potencia_sim_kw * df_day["fraccion_uso"]).round(4)
    df_day["coste_sel_eur"] = (
        df_day["consumo_sel_kwh"] * df_day["precio_eur_kwh"]
    ).round(4)

    # 1. Tabla de la franja óptima consecutiva
    st.subheader(
        f"Franja óptima consecutiva ({franja_optima_str}) · {watts_sel} W · {texto_duracion}"
    )
    df_on = df_day[df_day["estado_sel"] == "ON"].sort_values("hora").copy()

    tabla_resumen = pd.DataFrame(
        {
            "Hora": df_on["hora_label"],
            "Uso en esta hora": df_on["fraccion_uso"].apply(
                lambda f: "60 min (100%)" if f >= 0.999 else f"{int(round(f * 60))} min ({f*100:.0f}%)"
            ),
            "Tramo PVPC": df_on["tramo_pvpc"],
            "Semáforo": "🟢 ON (VERDE)",
            "Precio (€/kWh)": df_on["precio_eur_kwh"].map(lambda x: f"{x:.4f} €/kWh"),
            "Coste tramo (€)": df_on["coste_sel_eur"].map(lambda x: f"{x:.4f} €"),
        }
    )
    st.dataframe(tabla_resumen, use_container_width=True, hide_index=True)

    # 2. KPIs del ciclo
    coste_total_ciclo = float(df_day["coste_sel_eur"].sum())
    consumo_total_ciclo = float(df_day["consumo_sel_kwh"].sum())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Coste óptimo ciclo",
        f"{coste_total_ciclo:.2f} €",
        delta=f"{-ahorro_diferido:+.2f} € vs ahora ({hora_ahora:02d}:00)",
        delta_color="inverse",
    )
    k2.metric("Consumo ciclo", f"{consumo_total_ciclo:.2f} kWh")
    k3.metric("Franja óptima", franja_optima_str)
    k4.metric("Coste si lo pones ahora", f"{coste_ahora:.2f} €")

    st.divider()

    # 3. Gráfico 24h PVPC (Verde/Rojo)
    st.subheader(f"Planificación 24h: Precio PVPC ({watts_sel} W · {texto_duracion})")
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
                alt.Tooltip("consumo_sel_kwh:Q", title="Consumo (kWh)", format=".3f"),
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
                "fraccion_uso",
                "precio_eur_kwh",
                "consumo_sel_kwh",
                "coste_sel_eur",
            ]
        ].rename(
            columns={
                "hora_label": "Hora",
                "tramo_pvpc": "Tramo PVPC",
                "estado_sel": "Estado",
                "fraccion_uso": "Fracción hora",
                "precio_eur_kwh": "Precio (€/kWh)",
                "consumo_sel_kwh": "Consumo (kWh)",
                "coste_sel_eur": "Coste (€)",
            }
        )
        st.dataframe(detalle, use_container_width=True, hide_index=True)