-- Saved allocations: daily offline sales of each saved store x SKU from the allocation date to yesterday (IST).
-- {LOG_SRC} = SNITCH_DB.MAPLEMONK.TW_ALLOC_LOG, or an inline VALUES list when that table is not available.
-- Same exclusions as the engine's sales (doc prefixes, marketplaces). DAY_OFF 0 = the allocation date.
WITH l AS (
    SELECT DISTINCT ALLOC_ID, ALLOC_DATE::DATE AS ALLOC_DATE, BC::NUMBER AS BC, UPPER(SKU) AS SKU FROM {LOG_SRC}
)
SELECT l.ALLOC_ID, l.BC, l.SKU,
       DATEDIFF(DAY, l.ALLOC_DATE, s.ORDER_DATE)                                    AS DAY_OFF,
       SUM(COALESCE(s.SUBORDER_QUANTITY, 1))                                         AS UNITS,
       SUM(COALESCE(TRY_TO_NUMBER(s.SELLING_PRICE), 0) * COALESCE(s.SUBORDER_QUANTITY, 1)) AS REV
FROM l
JOIN SNITCH_DB.MAPLEMONK.STORE_FACT_ITEMS_OFFLINE s
  ON UPPER(s.SKU_GROUP) = l.SKU AND TRY_TO_NUMBER(s.BRANCH_CODE) = l.BC
 AND s.ORDER_DATE >= l.ALLOC_DATE AND s.ORDER_DATE < CURRENT_DATE()
WHERE COALESCE(s.DOC_PREFIX, '') NOT IN ({EXCL_DOC_PREFIX})
  AND s.MARKETPLACE_MAPPED NOT IN ({EXCL_MARKETPLACES})
GROUP BY 1, 2, 3, 4
