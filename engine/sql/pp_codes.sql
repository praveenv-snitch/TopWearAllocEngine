-- Prepack serial codes physically on hand (LIVE_INV_WAREHOUSE_OFFLINE_REPLEN, store_replen_prepack pack_rows):
-- one code = one sealed pack, e.g. PP6-4MSS4868-02-000024-15 -> style 4MSS4868-02, depth 6. Facility SAPL-NORTH-TAURU = North.
SELECT UPPER(SKU)                                                                          AS CODE,
       IFF(FACILITY = 'SAPL-NORTH-TAURU', 'NORTH', 'SOUTH')                                AS ZONE,
       SPLIT_PART(REGEXP_REPLACE(UPPER(SKU), '-[^-]+$', ''), '-', 2) || '-' ||
       SPLIT_PART(REGEXP_REPLACE(UPPER(SKU), '-[^-]+$', ''), '-', 3)                       AS SKU,
       TRY_TO_NUMBER(REGEXP_SUBSTR(UPPER(SKU), '^PP([0-9]+)', 1, 1, 'e'))                  AS DEPTH,
       SUM(UNITS_ON_HAND)                                                                  AS UNITS
FROM SNITCH_DB.MAPLEMONK.LIVE_INV_WAREHOUSE_OFFLINE_REPLEN
WHERE UPPER(SKU) LIKE 'PP%' AND COALESCE(UNITS_ON_HAND, 0) > 0
  AND UPPER(SKU) NOT REGEXP '^PP[0-9]+-(4BSFS|4MBGS|4BSHS|4BRN|4BPL).*'   -- plus-size packs excluded
GROUP BY 1, 2, 3, 4
