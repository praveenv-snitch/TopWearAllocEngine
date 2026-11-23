-- Store x SKU facts for in-scope categories: stock (on hand + JIT, by size), sales windows, ROS, STR inputs,
-- freshness (first stock day at the store), cut flag, last sale. Rows with stock now or any lifetime sale.
WITH om0 AS (
    SELECT om.*, UPPER(TRIM(om.SKU_GROUP)) s, om.BRANCH_CODE::INT bc, {OM_CAT_SYN} cat_syn,
           CASE WHEN UPPER(TRIM(om.SKU_GROUP)) LIKE 'MP-4%' THEN SUBSTR(UPPER(TRIM(om.SKU_GROUP)), 4)
                ELSE UPPER(TRIM(om.SKU_GROUP)) END b
    FROM SNITCH_DB.MAPLEMONK.OFFLINE_MASTER om
    WHERE om.BRANCH_CODE NOT IN ({EXCL_BRANCHES})
      AND om.MARKETPLACE_MAPPED NOT IN ({EXCL_MARKETPLACES})
      AND {OM_SKU_EXCL}
      AND (COALESCE(om.INVENTORY, 0) + COALESCE(om.JIT_QTY, 0) > 0 OR COALESCE(om.TOTAL_SALES, 0) > 0)
),
om AS (
    SELECT * FROM om0 WHERE COALESCE(cat_syn, {CATEGORY_PREFIX_CASE}) IN ({CATS})
      AND s NOT LIKE 'MP%'
),
opening_inv AS (            -- stock ~30 days ago (STR denominator, same as IST)
    SELECT UPPER(SKU_GROUP) s, BRANCH_CODE::INT bc, SUM(INVENTORY) OPEN_INV
    FROM SNITCH_DB.MAPLEMONK.OFFLINE_MASTER_DAILY_REPORT_1
    WHERE DATE = (SELECT MIN(DATE) FROM SNITCH_DB.MAPLEMONK.OFFLINE_MASTER_DAILY_REPORT_1
                  WHERE DATE >= DATEADD(DAY, -30, CURRENT_DATE()))
      AND BRANCH_CODE NOT IN ({EXCL_BRANCHES})
    GROUP BY 1, 2
),
first_inv AS (              -- first day the store held the style (freshness / age)
    SELECT UPPER(SKU_GROUP) s, BRANCH_CODE::INT bc, MIN(DATE) FIRST_STOCK_DT
    FROM SNITCH_DB.MAPLEMONK.OFFLINE_MASTER_DAILY_REPORT_1
    WHERE INVENTORY > 0 AND BRANCH_CODE NOT IN ({EXCL_BRANCHES})
    GROUP BY 1, 2
),
sales AS (
    SELECT UPPER(SKU_GROUP) s, TRY_TO_NUMBER(BRANCH_CODE) bc, MAX(ORDER_DATE) LAST_SALE,
           SUM(IFF(ORDER_DATE >= DATEADD(DAY, -90, CURRENT_DATE()), COALESCE(SUBORDER_QUANTITY, 1), 0)) L90,
           SUM(IFF(ORDER_DATE >= DATEADD(DAY, -90, CURRENT_DATE()),
                   COALESCE(TRY_TO_NUMBER(SELLING_PRICE), 0) * COALESCE(SUBORDER_QUANTITY, 1), 0)) REV90
    FROM SNITCH_DB.MAPLEMONK.STORE_FACT_ITEMS_OFFLINE
    WHERE COALESCE(DOC_PREFIX, '') NOT IN ({EXCL_DOC_PREFIX})
      AND MARKETPLACE_MAPPED NOT IN ({EXCL_MARKETPLACES})
    GROUP BY 1, 2
)
SELECT
    om.bc                                                      AS BC,
    om.s                                                       AS SKU,
    COALESCE(om.INVENTORY, 0)                                  AS INV,
    COALESCE(om.JIT_QTY, 0)                                    AS JIT,
    ARRAY_CONSTRUCT(
      COALESCE(om.XS_UNITS,0) +COALESCE(om.JIT_XS_UNITS,0),  COALESCE(om.S_UNITS,0)  +COALESCE(om.JIT_S_UNITS,0),
      COALESCE(om.M_UNITS,0)  +COALESCE(om.JIT_M_UNITS,0),   COALESCE(om.L_UNITS,0)  +COALESCE(om.JIT_L_UNITS,0),
      COALESCE(om.XL_UNITS,0) +COALESCE(om.JIT_XL_UNITS,0),  COALESCE(om.XXL_UNITS,0)+COALESCE(om.JIT_2XL_UNITS,0),
      COALESCE(om.XL3_UNITS,0)+COALESCE(om.JIT_3XL_UNITS,0), COALESCE(om.XL4_UNITS,0)+COALESCE(om.JIT_4XL_UNITS,0),
      COALESCE(om.XL5_UNITS,0)+COALESCE(om.JIT_5XL_UNITS,0), COALESCE(om.XL6_UNITS,0)+COALESCE(om.JIT_6XL_UNITS,0)) AS SZ,
    COALESCE(om.SALES_LAST_7_DAYS, 0)                          AS L7,
    COALESCE(om.SALES_LAST_15_DAYS, 0)                         AS L15,
    COALESCE(om.SALES_LAST_30_DAYS, 0)                         AS L30,
    COALESCE(sa.L90, 0)                                        AS L90,
    COALESCE(sa.REV90, 0)                                      AS REV90,
    COALESCE(om.TOTAL_SALES, 0)                                AS TOTAL_SALES,
    COALESCE(om.TOTAL_RETURNS, 0)                              AS TOTAL_RETURNS,
    ROUND(COALESCE(om.FINAL_ROS, 0), 4)                        AS ROS,
    ROUND(COALESCE(om.NATURAL_ROS, 0), 4)                      AS NROS,
    om.FIRST_ORDER_DATE,
    COALESCE(om.DAYS_SINCE_FIRST_ORDER, 0)                     AS DAYS_LIVE,
    IFF(UPPER(om.CUT_SIZE_WITH_JIT_FLAG) = 'YES', 1, 0)        AS IS_CUT,
    COALESCE(om.FRESH_INVENTORY, 0)                            AS FRESH_INV,
    IFF(COALESCE(oi.OPEN_INV, 0) > 0, oi.OPEN_INV,
        COALESCE(om.INVENTORY, 0) + COALESCE(om.SALES_LAST_30_DAYS, 0)) AS STR_DEN,
    COALESCE(om.SALES_LAST_30_DAYS, 0)                         AS STR_NUM,
    DATEDIFF(DAY, LEAST(COALESCE(fi.FIRST_STOCK_DT, '9999-12-31'::DATE),
                        COALESCE(om.FIRST_ORDER_DATE, '9999-12-31'::DATE)), CURRENT_DATE()) AS AGE_DAYS,
    DATEDIFF(DAY, sa.LAST_SALE, CURRENT_DATE())                AS LAST_SALE_DAYS
FROM om
LEFT JOIN opening_inv oi ON oi.s = om.s AND oi.bc = om.bc
LEFT JOIN first_inv fi   ON fi.s = om.s AND fi.bc = om.bc
LEFT JOIN sales sa       ON sa.s = om.s AND sa.bc = om.bc
