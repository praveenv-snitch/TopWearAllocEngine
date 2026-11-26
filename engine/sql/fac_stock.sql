-- Facility-level stock (LIVE_INV_WAREHOUSE_OFFLINE_REPLEN): the South zone has two warehouses (SAPL-WH1, SAPL-WH2),
-- North is SAPL-NORTH-TAURU. Used to put the exact facility against each row of the allocation download.
SELECT FACILITY,
       UPPER(REGEXP_REPLACE(SKU, '-[^-]+$', ''))          AS SKU,
       UPPER(REGEXP_SUBSTR(SKU, '[^-]+$'))                AS SZ,
       SUM(UNITS_ON_HAND)                                 AS UNITS
FROM SNITCH_DB.MAPLEMONK.LIVE_INV_WAREHOUSE_OFFLINE_REPLEN
WHERE UPPER(SKU) NOT LIKE 'PP%' AND COALESCE(UNITS_ON_HAND, 0) > 0 AND {PLUS_EXCL_SKU}
  AND UPPER(SKU) REGEXP '^4(MSS|MSN|SHS|LSHS|BSHS|SFS|LSFS|BSFS|MST|RN|LRN|BRN|PL|LPL|BPL).*'
GROUP BY 1, 2, 3
