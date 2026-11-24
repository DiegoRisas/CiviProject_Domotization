{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['fecha_hora_pk', 'dispositivo_sk'],
    on_schema_change='append_new_columns'
) }}

with precios as (
    select
        fecha_hora_pk,
        fecha,
        precio_eur_kwh
    from {{ ref('slv_energia__precios_pvpc') }}
    {% if is_incremental() %}
    where fecha >= (
        select dateadd('hour', -{{ var('lookback_hours', 48) }}, max(fecha_hora_pk))::date
        from {{ this }}
    )
    {% endif %}
),

clima as (
    select
        fecha_hora_pk,
        temperatura_ext_c
    from {{ ref('slv_clima__prediccion_horaria') }}
    where ubicacion = 'Granada'
),

sensores as (
    select
        fecha_hora_pk,
        habitacion_id,
        temp_interior_c,
        humedad_interior_pct
    from {{ ref('slv_domotica__lecturas_sensores') }}
),

tiempo as (
    select
        fecha_hora_pk,
        fecha,
        hora
    from {{ ref('dim_tiempo_horario') }}
),

dispositivos as (
    select
        dispositivo_sk,
        tipo_dispositivo,
        habitacion_id,
        habitacion_sk,
        potencia_nominal_kw,
        horas_base_dia
    from {{ ref('dim_dispositivos') }}
    where tipo_dispositivo != 'termo'
),

habitaciones as (
    select
        habitacion_sk,
        temp_confort_min_c,
        temp_confort_max_c
    from {{ ref('dim_habitaciones') }}
),

base as (
    select
        p.fecha_hora_pk,
        t.fecha,
        t.hora,
        d.dispositivo_sk,
        d.tipo_dispositivo,
        d.habitacion_sk,
        d.potencia_nominal_kw,
        d.horas_base_dia,
        p.precio_eur_kwh,
        c.temperatura_ext_c,
        s.temp_interior_c,
        s.humedad_interior_pct,
        h.temp_confort_min_c,
        h.temp_confort_max_c,
        round(
            greatest(0.0, coalesce(h.temp_confort_min_c - s.temp_interior_c, 0.0)),
            2
        ) as deficit_termico_c,
        coalesce(s.temp_interior_c < h.temp_confort_min_c, false) as necesita_calor
    from precios as p
    inner join tiempo as t
        on p.fecha_hora_pk = t.fecha_hora_pk
    left join clima as c
        on p.fecha_hora_pk = c.fecha_hora_pk
    cross join dispositivos as d
    left join habitaciones as h
        on d.habitacion_sk = h.habitacion_sk
    left join sensores as s
        on p.fecha_hora_pk = s.fecha_hora_pk
        and d.habitacion_id = s.habitacion_id
),

calculos_dia as (
    select
        *,
        sum(case when necesita_calor then 1 else 0 end) over (
            partition by fecha, dispositivo_sk
        ) as horas_con_frio_dia,
        case
            when tipo_dispositivo = 'calefactor_portatil' then
                row_number() over (
                    partition by fecha, dispositivo_sk
                    order by necesita_calor desc, precio_eur_kwh asc, deficit_termico_c desc, hora asc
                )
            else
                row_number() over (
                    partition by fecha, dispositivo_sk
                    order by precio_eur_kwh asc, hora asc
                )
        end as ranking_prioridad_dia
    from base
),

planificado as (
    select
        *,
        case
            when tipo_dispositivo = 'calefactor_portatil' then
                case
                    when horas_con_frio_dia = 0 then 0
                    else least(
                        horas_con_frio_dia,
                        {{ var('max_horas_calefaccion_dia', 8) }},
                        greatest(1, ceil(horas_con_frio_dia * {{ var('ratio_cobertura_calefaccion', 0.5) }}))
                    )
                end
            else coalesce(horas_base_dia, 1)
        end::integer as horas_minimas_recomendadas_dia
    from calculos_dia
)

select
    fecha_hora_pk,
    fecha,
    dispositivo_sk,
    habitacion_sk,
    precio_eur_kwh,
    temperatura_ext_c,
    temp_interior_c,
    humedad_interior_pct,
    deficit_termico_c,
    necesita_calor,
    horas_con_frio_dia::integer as horas_con_frio_dia,
    horas_minimas_recomendadas_dia,
    ranking_prioridad_dia::integer as ranking_prioridad_dia,
    case
        when ranking_prioridad_dia <= horas_minimas_recomendadas_dia then 'ON'
        else 'OFF'
    end as estado_default,
    case
        when ranking_prioridad_dia <= horas_minimas_recomendadas_dia then 'VERDE'
        else 'ROJO'
    end as color_semaforo_default,
    potencia_nominal_kw as consumo_si_on_kwh,
    round(potencia_nominal_kw * precio_eur_kwh, 4) as coste_si_on_eur,
    case
        when ranking_prioridad_dia <= horas_minimas_recomendadas_dia then potencia_nominal_kw
        else 0.0
    end as consumo_default_kwh,
    round(
        case
            when ranking_prioridad_dia <= horas_minimas_recomendadas_dia then potencia_nominal_kw * precio_eur_kwh
            else 0.0
        end,
        4
    ) as coste_default_eur
from planificado