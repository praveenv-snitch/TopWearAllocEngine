-- Fresh pool (store_avail.py logic): WH styles with full size sets or prepack sets, per zone, from AV_MASTER_HTMBASE.
-- FULL_SIZE_OPTIONS = full loose size sets the zone can build; size units are after the WH buffer.
SELECT UPPER(SKU_GROUP)                                 AS SKU,
       UPPER(WAREHOUSE_LOCATION)                        AS ZONE,
       MAX(ALLOCATION_STATUS)                           AS ALLOCATION_STATUS,
       SUM(COALESCE(FULL_SIZE_OPTIONS, 0))              AS FSO,
       SUM(COALESCE(XS_UNITS, 0)) XS, SUM(COALESCE(S_UNITS, 0)) S, SUM(COALESCE(M_UNITS, 0)) M, SUM(COALESCE(L_UNITS, 0)) L,
       SUM(COALESCE(XL_UNITS, 0)) XL, SUM(COALESCE(XXL_UNITS, 0)) XXL, SUM(COALESCE(XL3_UNITS, 0)) XL3,
       SUM(COALESCE(XL4_UNITS, 0)) XL4, SUM(COALESCE(XL5_UNITS, 0)) XL5, SUM(COALESCE(XL6_UNITS, 0)) XL6,
       MAX(COALESCE(PREPACK_DEPTH, 0))                  AS PP_DEPTH,
       SUM(COALESCE(PREPACK_SETS, 0))                   AS PP_SETS
FROM SNITCH_DB.MAPLEMONK.AV_MASTER_HTMBASE
WHERE UPPER(CATEGORY) IN ({CATS})
  AND (COALESCE(FULL_SIZE_OPTIONS, 0) > 0 OR COALESCE(PREPACK_SETS, 0) > 0)
  AND UPPER(SKU_GROUP) NOT LIKE 'MP%' AND UPPER(SKU_GROUP) NOT LIKE 'PP%' AND {PLUS_EXCL}   -- plus-size styles excluded
  AND UPPER(COALESCE(STYLE, '')) NOT LIKE 'MP%'
GROUP BY 1, 2
