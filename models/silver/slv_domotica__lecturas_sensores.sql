{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['fecha_hora_pk', 'habitacion_id'],
    on_schema_change='append_new_columns'
) }}

with stg as (
    select * from {{ ref('stg_domotica__sensores_interiores') }}
    {% if is_incremental() %}
    where fecha_hora_pk >= (
        select dateadd('hour', -{{ var('lookback_hours', 48) }}, max(fecha_hora_pk))
        from {{ this }}
    )
    {% endif %}
),

dedup as (
    select
        fecha_hora_lectura,
        fecha_hora_pk,
        habitacion_id,
        temp_interior_c,
        humedad_interior_pct,
        ingested_at
    from stg
    qualify row_number() over (
        partition by fecha_hora_lectura, habitacion_id
        order by ingested_at desc
    ) = 1
)

select
    fecha_hora_pk,
    fecha_hora_pk::date                         as fecha,
    extract(hour from fecha_hora_pk)::integer   as hora,
    habitacion_id,
    round(avg(temp_interior_c), 2)::float       as temp_interior_c,
    round(min(temp_interior_c), 2)::float       as temp_interior_min_c,
    round(max(temp_interior_c), 2)::float       as temp_interior_max_c,
    round(avg(humedad_interior_pct), 2)::float  as humedad_interior_pct,
    count(*)::integer                           as num_lecturas,
    max(ingested_at)                            as ingested_at
from dedup
group by 1, 2, 3, 4