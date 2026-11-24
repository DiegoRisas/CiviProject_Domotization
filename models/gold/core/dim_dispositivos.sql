with catalogo as (
    select * from {{ ref('catalogo_dispositivos') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['dispositivo_id']) }} as dispositivo_sk,
    dispositivo_id,
    nombre_dispositivo,
    tipo_dispositivo,
    habitacion,
    potencia_nominal_kw,
    capacidad_litros,
    horas_base_dia
from catalogo