with dispositivos as (
    select * from {{ ref('slv_domotica__dispositivos') }}
),

habitaciones as (
    select * from {{ ref('dim_habitaciones') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['d.dispositivo_id']) }} as dispositivo_sk,
    d.dispositivo_id,
    d.nombre_dispositivo,
    d.tipo_dispositivo,
    d.habitacion_id,
    h.habitacion_sk,
    h.nombre_habitacion,
    d.potencia_nominal_kw,
    d.capacidad_litros,
    d.horas_base_dia
from dispositivos as d
left join habitaciones as h
    on d.habitacion_id = h.habitacion_id