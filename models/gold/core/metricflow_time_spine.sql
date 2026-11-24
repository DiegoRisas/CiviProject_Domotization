{{ config(materialized='table') }}

with hours as (
    {{ dbt_utils.date_spine(
        datepart="hour",
        start_date="cast('2025-01-01 00:00:00' as timestamp_ntz)",
        end_date="cast('2027-12-31 23:00:00' as timestamp_ntz)"
    ) }}
)

select
    cast(date_hour as timestamp_ntz) as date_hour
from hours