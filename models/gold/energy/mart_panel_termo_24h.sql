{{ config(materialized='view') }}

with hechos as (
    select * from {{ ref('fct_plan_termo_horario') }}
),

tiempo as (
    select * from {{ ref('dim_tiempo_horario') }}
),

termo as (
    select * from {{ ref('dim_termo') }}
)

select
    h.fecha_hora_pk::timestamp_ntz                                                      as fecha_hora_pk,
    t.fecha::date                                                                       as fecha,
    t.hora::integer                                                                     as hora,
    t.dia_semana::varchar                                                               as dia_semana,
    t.tramo_pvpc::varchar                                                               as tramo_pvpc,
    t.bloque_dia::varchar                                                               as bloque_dia,
    d.dispositivo_id::varchar                                                           as dispositivo_id,
    d.nombre_dispositivo::varchar                                                       as nombre_dispositivo,
    h.precio_eur_kwh::float                                                             as precio_eur_kwh,
    h.temperatura_ext_c::float                                                          as temperatura_ext_c,
    h.temp_media_dia_c::float                                                           as temp_media_dia_c,
    h.es_dia_frio::boolean                                                              as es_dia_frio,
    h.estado_termo::varchar                                                             as estado_termo,
    h.color_semaforo::varchar                                                           as color_semaforo,
    h.consumo_estimado_kwh::float                                                       as consumo_estimado_kwh,
    h.coste_estimado_eur::float                                                         as coste_estimado_eur,
    sum(h.consumo_estimado_kwh) over (partition by t.fecha, d.dispositivo_id)::float    as consumo_total_dia_kwh,
    round(sum(h.coste_estimado_eur) over (partition by t.fecha, d.dispositivo_id), 4)::float as coste_total_dia_eur,
    count_if(h.estado_termo = 'ON') over (partition by t.fecha, d.dispositivo_id)::integer   as total_horas_on_dia
from hechos as h
inner join tiempo as t
    on h.fecha_hora_pk = t.fecha_hora_pk
inner join termo as d
    on h.termo_sk = d.termo_sk