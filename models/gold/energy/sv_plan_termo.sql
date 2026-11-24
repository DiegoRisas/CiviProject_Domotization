{{ config(
    materialized='semantic_view',
    copy_grants=true
) }}

TABLES (
    plan_termo AS {{ ref('fct_plan_termo_horario') }}
        PRIMARY KEY (fecha_hora_pk, termo_sk)
        COMMENT = 'Plan horario ON/OFF, consumo y coste estimado del termo eléctrico',
    tiempo AS {{ ref('dim_tiempo_horario') }}
        PRIMARY KEY (fecha_hora_pk)
        COMMENT = 'Calendario horario con tramos PVPC 2.0TD y bloques del día',
    termo AS {{ ref('dim_termo') }}
        PRIMARY KEY (termo_sk)
        COMMENT = 'Características técnicas del termo eléctrico'
)

RELATIONSHIPS (
    plan_to_tiempo AS plan_termo (fecha_hora_pk) REFERENCES tiempo (fecha_hora_pk),
    plan_to_termo  AS plan_termo (termo_sk)      REFERENCES termo (termo_sk)
)

FACTS (
    plan_termo.coste_estimado_eur   AS coste_estimado_eur,
    plan_termo.consumo_estimado_kwh AS consumo_estimado_kwh,
    plan_termo.precio_eur_kwh       AS precio_eur_kwh,
    plan_termo.temperatura_ext_c    AS temperatura_ext_c
)

DIMENSIONS (
    tiempo.fecha_hora_pk      AS fecha_hora_pk,
    tiempo.fecha              AS fecha
        WITH SYNONYMS = ('dia', 'fecha natural'),
    tiempo.hora               AS hora
        WITH SYNONYMS = ('franja horaria'),
    tiempo.dia_semana         AS dia_semana,
    tiempo.es_fin_de_semana   AS es_fin_de_semana,
    tiempo.anio_mes           AS anio_mes
        WITH SYNONYMS = ('mes'),
    tiempo.tramo_pvpc         AS tramo_pvpc
        WITH SYNONYMS = ('periodo tarifario', 'tarifa', 'valle llano punta'),
    tiempo.bloque_dia         AS bloque_dia
        WITH SYNONYMS = ('bloque', 'franja del dia'),
    termo.dispositivo_id      AS dispositivo_id,
    termo.nombre_dispositivo  AS nombre_dispositivo,
    plan_termo.estado_termo   AS estado_termo
        WITH SYNONYMS = ('estado', 'encendido apagado'),
    plan_termo.color_semaforo AS color_semaforo
        WITH SYNONYMS = ('semaforo'),
    plan_termo.es_dia_frio    AS es_dia_frio
)

METRICS (
    plan_termo.coste_termo_eur AS SUM(plan_termo.coste_estimado_eur)
        WITH SYNONYMS = ('coste termo', 'gasto termo', 'coste euros')
        COMMENT = 'Coste eléctrico total estimado del termo en euros',
    plan_termo.consumo_termo_kwh AS SUM(plan_termo.consumo_estimado_kwh)
        WITH SYNONYMS = ('consumo termo', 'energia kwh')
        COMMENT = 'Consumo eléctrico total estimado del termo en kWh',
    plan_termo.horas_encendido AS SUM(CASE WHEN plan_termo.estado_termo = 'ON' THEN 1 ELSE 0 END)
        WITH SYNONYMS = ('horas ON', 'horas encendido')
        COMMENT = 'Número total de horas con el termo encendido (ON)',
    plan_termo.precio_medio_efectivo_eur_kwh AS SUM(plan_termo.coste_estimado_eur) / NULLIF(SUM(plan_termo.consumo_estimado_kwh), 0)
        WITH SYNONYMS = ('precio medio efectivo', 'coste por kwh')
        COMMENT = 'Precio real medio por kWh durante las horas de encendido del termo'
)

COMMENT = 'Vista semántica gobernada del plan horario del termo eléctrico (Gold)'