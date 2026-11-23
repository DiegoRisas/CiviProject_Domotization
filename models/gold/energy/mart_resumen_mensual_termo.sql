{{ config(materialized='view') }}

with hechos as (
    select * from {{ ref('fct_plan_termo_horario') }}
),

tiempo as (
    select * from {{ ref('dim_tiempo_horario') }}
),

termo as (
    select * from {{ ref('dim_termo') }}
),

diario as (
    select
        t.anio::integer                                         as anio,
        t.anio_mes::varchar                                     as anio_mes,
        date_trunc('month', t.fecha)::date                      as mes_inicio,
        t.fecha::date                                           as fecha,
        d.dispositivo_id::varchar                               as dispositivo_id,
        d.nombre_dispositivo::varchar                           as nombre_dispositivo,
        day(last_day(t.fecha))::integer                         as dias_totales_mes,
        count_if(h.estado_termo = 'ON')::integer                as horas_on_dia,
        sum(h.consumo_estimado_kwh)::float                      as consumo_dia_kwh,
        sum(h.coste_estimado_eur)::float                        as coste_dia_eur,
        avg(h.precio_eur_kwh)::float                            as precio_medio_dia_eur_kwh
    from hechos as h
    inner join tiempo as t
        on h.fecha_hora_pk = t.fecha_hora_pk
    inner join termo as d
        on h.termo_sk = d.termo_sk
    group by 1, 2, 3, 4, 5, 6, 7
),

acumulado_mtd as (
    select
        anio,
        anio_mes,
        mes_inicio,
        fecha,
        dispositivo_id,
        nombre_dispositivo,
        dias_totales_mes,
        count(*) over (
            partition by anio_mes, dispositivo_id
            order by fecha
            rows between unbounded preceding and current row
        )::integer                                              as dias_acumulados,
        sum(horas_on_dia) over (
            partition by anio_mes, dispositivo_id
            order by fecha
            rows between unbounded preceding and current row
        )::integer                                              as total_horas_on_mes,
        round(
            sum(consumo_dia_kwh) over (
                partition by anio_mes, dispositivo_id
                order by fecha
                rows between unbounded preceding and current row
            ),
            2
        )::float                                                as consumo_mes_kwh,
        round(
            sum(coste_dia_eur) over (
                partition by anio_mes, dispositivo_id
                order by fecha
                rows between unbounded preceding and current row
            ),
            2
        )::float                                                as coste_mes_eur,
        round(
            avg(precio_medio_dia_eur_kwh) over (
                partition by anio_mes, dispositivo_id
                order by fecha
                rows between unbounded preceding and current row
            ),
            4
        )::float                                                as precio_medio_mes_eur_kwh
    from diario
)

select
    anio,
    anio_mes,
    mes_inicio,
    fecha,
    dispositivo_id,
    nombre_dispositivo,
    dias_acumulados,
    dias_totales_mes,
    (dias_acumulados = dias_totales_mes)::boolean               as es_mes_completo,
    case
        when dias_acumulados = dias_totales_mes then 'Mes completo'
        else 'Acumulado hasta ' || to_char(fecha, 'DD/MM')
    end::varchar                                                as estado_mes,
    total_horas_on_mes,
    consumo_mes_kwh,
    coste_mes_eur,
    round(
        case
            when dias_acumulados = dias_totales_mes then coste_mes_eur
            else (coste_mes_eur / nullif(dias_acumulados, 0)) * dias_totales_mes
        end,
        2
    )::float                                                    as coste_proyectado_mes_eur,
    precio_medio_mes_eur_kwh
from acumulado_mtd