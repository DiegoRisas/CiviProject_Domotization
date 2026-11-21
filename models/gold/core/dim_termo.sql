with termo as (
    select * from {{ ref('catalogo_termo') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['dispositivo_id']) }} as termo_sk,
    dispositivo_id,
    nombre_dispositivo,
    capacidad_litros,
    potencia_nominal_kw,
    horas_base_dia
from termo