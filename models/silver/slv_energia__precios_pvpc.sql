{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='fecha_hora_pk',
    on_schema_change='append_new_columns'
) }}

with stg as (
    select * from {{ ref('stg_ree__pvpc') }}
    {% if is_incremental() %}
    where fecha_hora_pk >= (
        select dateadd('hour', -{{ var('lookback_hours', 48) }}, max(fecha_hora_pk))
        from {{ this }}
    )
    {% endif %}
)

select
    fecha_hora_pk,
    fecha_hora_pk::date                         as fecha,
    extract(hour from fecha_hora_pk)::integer   as hora,
    indicador_id,
    tarifa,
    precio_eur_mwh,
    precio_eur_kwh,
    ingested_at
from stg
qualify row_number() over (
    partition by fecha_hora_pk
    order by ingested_at desc
) = 1