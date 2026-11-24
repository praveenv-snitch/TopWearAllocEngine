-- Units already dispatched / in transit to stores per SKU via B2B (last 60 days) - used by Nudges and to avoid
-- re-allocating what is already on the way.
SELECT UPPER(REGEXP_REPLACE(SKU, '-[^-]+$', '')) AS SKU,
       UPPER(TRIM(FINAL_STORE))                  AS STORE,
       SUM(COALESCE(QTY, 0))                     AS QTY,
       SUM(IFF(INWARDED_DATE IS NULL, COALESCE(QTY, 0), 0)) AS IN_TRANSIT,
       MAX(INWARDED_DATE)                        AS LAST_INWARD
FROM SNITCH_DB.MAPLEMONK.B2B_JOURNEY
WHERE {PLUS_EXCL_SKU}
  AND UPPER(SKU) REGEXP '^4(MSS|MSN|SHS|LSHS|BSHS|SFS|LSFS|BSFS|MST|RN|LRN|BRN|PL|LPL|BPL).*'
GROUP BY 1, 2
