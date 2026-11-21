{% macro tramo_horario_pvpc(fecha_hora_col) -%}
    case
        when dayofweekiso({{ fecha_hora_col }}) in (6, 7) then 'Valle'
        when extract(hour from {{ fecha_hora_col }}) between 0 and 7 then 'Valle'
        when extract(hour from {{ fecha_hora_col }}) in (10, 11, 12, 13, 18, 19, 20, 21) then 'Punta'
        else 'Llano'
    end
{%- endmacro %}