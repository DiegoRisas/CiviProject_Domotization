select
    dispositivo_sk as termo_sk,
    dispositivo_id,
    nombre_dispositivo,
    capacidad_litros,
    potencia_nominal_kw,
    horas_base_dia
from {{ ref('dim_dispositivos') }}
where tipo_dispositivo = 'termo'