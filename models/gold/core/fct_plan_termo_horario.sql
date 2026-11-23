{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['fecha_hora_pk', 'termo_sk'],
    on_schema_change='append_new_columns'
) }}

with contexto as (
    select * from {{ ref('slv_energia__contexto_horario') }}
    {% if is_incremental() %}
    where fecha >= (
        select dateadd('hour', -{{ var('lookback_hours', 48) }}, max(fecha_hora_pk))::date
        from {{ this }}
    )
    {% endif %}
),

tiempo as (
    select * from {{ ref('dim_tiempo_horario') }}
),

termo as (
    select * from {{ ref('dim_termo') }}
),

base as (
    select
        c.fecha_hora_pk,
        t.fecha,
        t.hora,
        t.bloque_dia,
        d.termo_sk,
        d.potencia_nominal_kw,
        d.horas_base_dia,
        c.precio_eur_kwh,
        c.temperatura_ext_c,
        c.humedad_relativa_pct,
        avg(c.temperatura_ext_c) over (partition by t.fecha) as temp_media_dia_c,
        row_number() over (
            partition by t.fecha, d.termo_sk, t.bloque_dia
            order by c.precio_eur_kwh asc, t.hora asc
        ) as ranking_precio_bloque
    from contexto as c
    inner join tiempo as t
        on c.fecha_hora_pk = t.fecha_hora_pk
    cross join termo as d
),

plan_base as (
    select
        *,
        coalesce(temp_media_dia_c < {{ var('umbral_frio_ext_c', 10.0) }}, false) as es_dia_frio,
        case
            when bloque_dia = 'Madrugada'
                and ranking_precio_bloque <= (floor(horas_base_dia / 3) + case when mod(horas_base_dia, 3) >= 1 then 1 else 0 end)
                then true
            when bloque_dia = 'Mediodia'
                and ranking_precio_bloque <= (floor(horas_base_dia / 3) + case when mod(horas_base_dia, 3) >= 2 then 1 else 0 end)
                then true
            when bloque_dia = 'Tarde_Noche'
                and ranking_precio_bloque <= floor(horas_base_dia / 3)
                then true
            else false
        end as es_on_base
    from base
),

plan_con_frio as (
    select
        *,
        case
            when not es_on_base then
                row_number() over (
                    partition by fecha, termo_sk, es_on_base
                    order by precio_eur_kwh asc, hora asc
                )
        end as ranking_extra_frio
    from plan_base
),

final as (
    select
        fecha_hora_pk,
        fecha,
        termo_sk,
        precio_eur_kwh,
        ranking_precio_bloque,
        temperatura_ext_c,
        humedad_relativa_pct,
        round(temp_media_dia_c, 2) as temp_media_dia_c,
        es_dia_frio,
        case
            when es_on_base then 'ON'
            when es_dia_frio and ranking_extra_frio <= {{ var('horas_extra_frio', 1) }} then 'ON'
            else 'OFF'
        end as estado_termo,
        case
            when es_on_base then 'VERDE'
            when es_dia_frio and ranking_extra_frio <= {{ var('horas_extra_frio', 1) }} then 'VERDE'
            else 'ROJO'
        end as color_semaforo,
        case
            when es_on_base or (es_dia_frio and ranking_extra_frio <= {{ var('horas_extra_frio', 1) }})
                then potencia_nominal_kw
            else 0.0
        end as consumo_estimado_kwh,
        round(
            case
                when es_on_base or (es_dia_frio and ranking_extra_frio <= {{ var('horas_extra_frio', 1) }})
                    then potencia_nominal_kw * precio_eur_kwh
                else 0.0
            end,
            4
        ) as coste_estimado_eur
    from plan_con_frio
)

select * from final