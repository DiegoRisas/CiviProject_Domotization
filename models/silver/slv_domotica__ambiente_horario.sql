{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['fecha_hora_pk', 'habitacion'],
    on_schema_change='append_new_columns'
) }}

with sensores as (
    select * from {{ ref('stg_kaggle__sensores_interiores') }}
    {% if is_incremental() %}
    where fecha_hora_pk >= (
        select dateadd('hour', -{{ var('lookback_hours', 48) }}, max(fecha_hora_pk))
        from {{ this }}
    )
    {% endif %}
),

contexto as (
    select * from {{ ref('slv_energia__contexto_horario') }}
)

select
    s.fecha_hora_pk,
    s.fecha_hora_pk::date                                   as fecha,
    extract(hour from s.fecha_hora_pk)::integer             as hora,
    s.habitacion,
    s.temp_interior_c,
    s.temp_interior_min_c,
    s.temp_interior_max_c,
    s.num_lecturas,
    c.precio_eur_kwh,
    c.temperatura_ext_c,
    c.humedad_relativa_pct,
    round(s.temp_interior_c - c.temperatura_ext_c, 2)       as delta_termico_c,
    s.ingested_at                                           as sensor_ingested_at
from sensores as s
inner join contexto as c
    on s.fecha_hora_pk = c.fecha_hora_pk