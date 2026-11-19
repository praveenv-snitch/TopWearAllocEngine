-- Stock already moving WH -> store (B2B journey, not yet inwarded, last 30 days), per store x style.
-- Counted as "in pipe" so the allocation does not double-send. FRESH_DISPATCHED = first-time sends (nudge check).
SELECT UPPER(TRIM(FINAL_STORE)) STORE_NAME, UPPER(REGEXP_REPLACE(SKU,'-[^-]+$','')) SKU,
       SUM(IFF(FINAL_STATUS <> 'INWARDED', COALESCE(QTY,0), 0)) PIPE_QTY,
       SUM(IFF(TYPE ILIKE 'FRESH%', COALESCE(QTY,0), 0)) FRESH_SENT_30D
FROM SNITCH_DB.MAPLEMONK.B2B_JOURNEY
WHERE COALESCE(BILL_DATE, ORDER_DATE) >= DATEADD(DAY,-30,CURRENT_DATE())
  AND FINAL_STATUS <> 'EXCEPTION_LOST_DAMAGE'
  AND SKU IS NOT NULL
GROUP BY 1,2
