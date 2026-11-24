{{ config(materialized='view') }}

with hechos as (
    select * from {{ ref('fct_plan_dispositivos_horario') }}
),

tiempo as (
    select * from {{ ref('dim_tiempo_horario') }}
),

dispositivos as (
    select * from {{ ref('dim_dispositivos') }}
),

habitaciones as (
    select * from {{ ref('dim_habitaciones') }}
)

select
    h.fecha_hora_pk::timestamp_ntz                  as fecha_hora_pk,
    t.fecha::date                                   as fecha,
    t.hora::integer                                 as hora,
    t.dia_semana::varchar                           as dia_semana,
    t.tramo_pvpc::varchar                           as tramo_pvpc,
    t.bloque_dia::varchar                           as bloque_dia,
    d.dispositivo_id::varchar                       as dispositivo_id,
    d.nombre_dispositivo::varchar                   as nombre_dispositivo,
    d.tipo_dispositivo::varchar                     as tipo_dispositivo,
    hab.habitacion_id::varchar                      as habitacion_id,
    hab.nombre_habitacion::varchar                  as nombre_habitacion,
    d.potencia_nominal_kw::float                    as potencia_nominal_kw,
    h.precio_eur_kwh::float                         as precio_eur_kwh,
    h.temperatura_ext_c::float                      as temperatura_ext_c,
    h.temp_interior_c::float                        as temp_interior_c,
    h.humedad_interior_pct::float                   as humedad_interior_pct,
    hab.temp_confort_min_c::float                   as temp_confort_min_c,
    hab.temp_confort_max_c::float                   as temp_confort_max_c,
    h.deficit_termico_c::float                      as deficit_termico_c,
    h.necesita_calor::boolean                       as necesita_calor,
    h.horas_minimas_recomendadas_dia::integer       as horas_minimas_recomendadas_dia,
    h.ranking_prioridad_dia::integer                as ranking_prioridad_dia,
    h.estado_default::varchar                       as estado_default,
    h.consumo_si_on_kwh::float                      as consumo_si_on_kwh,
    h.coste_si_on_eur::float                        as coste_si_on_eur
from hechos as h
inner join tiempo as t
    on h.fecha_hora_pk = t.fecha_hora_pk
inner join dispositivos as d
    on h.dispositivo_sk = d.dispositivo_sk
inner join habitaciones as hab
    on h.habitacion_sk = hab.habitacion_sk