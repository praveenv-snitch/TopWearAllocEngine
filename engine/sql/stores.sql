-- One row per store x in-scope category: hierarchy, base stock, ideal category mix, depth (DEPT_IDEAL),
-- overall fill, MTD target vs actual, DOI cap, STORE_CATEGORY_DELTA net stock (JIT / IST), category target.
WITH om AS (
    SELECT om.*, om.BRANCH_CODE::INT bc,
           COALESCE({OM_CAT_SYN}, IFF(UPPER(om.SKU_GROUP) REGEXP '^4(MSS|MSN|SHS|LSHS|BSHS|SFS|LSFS|BSFS).*', 'SHIRTS',
                    IFF(UPPER(om.SKU_GROUP) REGEXP '^4(MST|RN|LRN|BRN|PL|LPL|BPL).*', 'T-SHIRTS', NULL))) cat_n
    FROM SNITCH_DB.MAPLEMONK.OFFLINE_MASTER om
    WHERE om.BRANCH_CODE NOT IN ({EXCL_BRANCHES})
      AND om.MARKETPLACE_MAPPED NOT IN ({EXCL_MARKETPLACES})
      AND {OM_SKU_EXCL}
),
store AS (
    SELECT bc,
           ANY_VALUE(MARKETPLACE_MAPPED)                                    STORE_NAME,
           MODE(UPPER(TRIM(NULLIF(STATE, ''))))                             STATE,
           MODE(UPPER(TRIM(NULLIF(CITY, ''))))                              CITY,
           MODE(UPPER(TRIM(NULLIF(REGION, ''))))                            REGION,
           MODE(NULLIF(CLUSTER, 'None'))                                    OM_CLUSTER,
           MAX(TRY_TO_NUMBER(REPLACE(CARPET_AREA, ',', '')))                CARPET_AREA,
           MAX(TRY_TO_NUMBER(BASE_STOCK))                                   OM_BASE_STOCK,
           SUM(IFF(UPPER(COALESCE(NEW_CATEGORY, '')) NOT IN ('ACCESSORIES','BAGS','BELTS','LUGGAGE','PERFUMES','SHOES','SUNGLASSES'),
                   COALESCE(INVENTORY, 0), 0))                              APPAREL_INV,
           ANY_VALUE(UPPER(TRIM(SPLIT_PART(MARKETPLACE_MAPPED, '-', 2))))   STORE_TYPE
    FROM om GROUP BY 1
),
cat AS (
    SELECT bc, cat_n CATEGORY,
           MODE(TRY_TO_NUMBER(DEPT_IDEAL))                                  DEPTH,
           SUM(COALESCE(INVENTORY, 0))                                      CAT_INV,
           SUM(COALESCE(JIT_QTY, 0))                                        CAT_JIT,
           COUNT(DISTINCT IFF(COALESCE(INVENTORY, 0) + COALESCE(JIT_QTY, 0) > 0, UPPER(SKU_GROUP), NULL)) OPTIONS,
           SUM(COALESCE(SALES_LAST_30_DAYS, 0))                             CAT_L30
    FROM om WHERE cat_n IN ({CATS}) GROUP BY 1, 2
),
mix AS (
    SELECT TRY_TO_NUMBER(STORE_CODE) bc, UPPER(CATEGORY) CATEGORY,
           MAX(TRY_TO_NUMBER(CATEGORY_MIX, 10, 4))                          IDEAL_CAT_MIX,
           MAX(TRY_TO_NUMBER(BASE_STOCK))                                   BASE_STOCK,
           MAX(UPPER(CLUSTER))                                              MIX_CLUSTER
    FROM SNITCH_DB.MAPLEMONK.GS_SHEET3 GROUP BY 1, 2
),
zone AS (
    SELECT BRANCH_CODE::INT bc, ANY_VALUE(CLUSTER_NAME) ZONE_CLUSTER, ANY_VALUE(UPPER(ZONE)) ZONE
    FROM SNITCH_DB.MAPLEMONK.STORE_ZONE_MAP GROUP BY 1
),
city AS (
    SELECT TRY_TO_NUMBER(BRANCH_CODE) bc, ANY_VALUE(CLUSTER_NAME) CITY_CLUSTER, ANY_VALUE(PIN_CODE) PINCODE,
           ANY_VALUE(STORE_STATUS) STORE_STATUS
    FROM SNITCH_DB.MAPLEMONK.STORE_CLUSTERS GROUP BY 1
),
tgt AS (   -- MTD_TARGET_CLEAN holds one row per store per month = full-month target; MTD = pro-rated to yesterday
    SELECT TRY_TO_NUMBER(BRANCH_CODE) bc,
           MAX(TRY_TO_NUMBER(REGEXP_REPLACE(TRIM(CUMULATIVE_TARGET_MTD::VARCHAR), '[^0-9.]', ''), 18, 2)) TARGET_MONTH,
           MAX(TRY_TO_NUMBER(REGEXP_REPLACE(TRIM(CUMULATIVE_TARGET_MTD::VARCHAR), '[^0-9.]', ''), 18, 2)) * DAY(DATEADD(DAY, -1, CURRENT_DATE())) / DAY(LAST_DAY(DATEADD(DAY, -1, CURRENT_DATE()))) TARGET_MTD
    FROM SNITCH_DB.MAPLEMONK.MTD_TARGET_CLEAN
    WHERE DATE_TRUNC('MONTH', TARGET_DATE) = DATE_TRUNC('MONTH', DATEADD(DAY, -1, CURRENT_DATE()))
    GROUP BY 1
),
scd AS (   -- STORE_CATEGORY_DELTA (size_category_meta_delta_offline): stock, JIT, IST in/out, ROS 7d x lead time, outward
    SELECT TRY_TO_NUMBER(BRANCH_CODE) bc, UPPER(CATEGORY) CATEGORY,
           SUM(COALESCE(INVENTORY, 0)) D_INV, SUM(COALESCE(JIT_QTY, 0)) D_JIT, SUM(COALESCE(IST_JIT_QTY, 0)) D_IST_IN,
           SUM(COALESCE(IST_GIVEN_QTY, 0)) D_IST_OUT, SUM(COALESCE(ROS_7D, 0)) D_ROS7, MAX(COALESCE(LEAD_TIME, 3)) D_LEAD,
           SUM(COALESCE(OUTWARD_QTY, 0)) D_OUTWARD, MAX(CATEGORY_BASE_STOCK) D_CAT_BASE, MAX(TRY_TO_NUMBER(BASE_STOCK)) D_BASE
    FROM SNITCH_DB.MAPLEMONK.STORE_CATEGORY_DELTA GROUP BY 1, 2
),
scd_store AS (   -- store level (all categories): current fill / after JIT / after IST, as in the delta file formulas
    SELECT bc, MAX(D_BASE) S_BASE, SUM(D_INV) S_INV,
           SUM(D_INV) + SUM(D_JIT) - SUM(D_ROS7) * MAX(D_LEAD) - SUM(D_OUTWARD)                                      S_NET_JIT,
           SUM(D_INV) + SUM(D_JIT) + SUM(D_IST_IN) - SUM(D_ROS7) * MAX(D_LEAD) - SUM(D_OUTWARD) - SUM(D_IST_OUT)     S_NET_IST
    FROM scd GROUP BY 1
),
ptgt AS (   -- category weight + category revenue this month (FACT_PARETO_TARGET_PERFORMANCE_SUMMARY, store wise).
            -- CATEGORY_TARGET is a full-month figure; category MTD target = it pro-rated to yesterday (computed below).
    SELECT TRY_TO_NUMBER(LOCATION_ID) bc, UPPER(CATEGORY) CATEGORY,
           MAX(STORE_MONTHLY_TARGET) STORE_MONTH_TARGET, MAX(WEIGHTED_CAT_TARGET_PCT) CAT_TARGET_WEIGHT,
           MAX(CATEGORY_TARGET) CAT_TARGET, MAX(TARGET_PCT_ACHIEVED) CAT_TARGET_PCT
    FROM SNITCH_DB.MAPLEMONK.FACT_PARETO_TARGET_PERFORMANCE_SUMMARY
    WHERE HIERARCHY_LEVEL = '3. Store Wise' AND REPORT_MONTH = TO_CHAR(DATEADD(DAY, -1, CURRENT_DATE()), 'YYYY-MM')
    GROUP BY 1, 2
),
act AS (
    SELECT TRY_TO_NUMBER(BRANCH_CODE) bc,
           SUM(COALESCE(TRY_TO_NUMBER(SELLING_PRICE), 0) * COALESCE(SUBORDER_QUANTITY, 1)) ACTUAL_MTD
    FROM SNITCH_DB.MAPLEMONK.STORE_FACT_ITEMS_OFFLINE
    WHERE ORDER_DATE >= DATE_TRUNC('MONTH', DATEADD(DAY, -1, CURRENT_DATE())) AND ORDER_DATE < CURRENT_DATE()
      AND COALESCE(DOC_PREFIX, '') NOT IN ({EXCL_DOC_PREFIX})
      AND MARKETPLACE_MAPPED NOT IN ({EXCL_MARKETPLACES})
    GROUP BY 1
)
SELECT s.bc AS BC, s.STORE_NAME, s.STORE_TYPE, s.STATE, s.CITY,
       COALESCE(z.ZONE, s.REGION)                                       AS ZONE,
       COALESCE(z.ZONE_CLUSTER, s.OM_CLUSTER, m.MIX_CLUSTER)            AS CLUSTER,
       c2.CITY_CLUSTER, c2.PINCODE, s.CARPET_AREA,
       COALESCE(m.BASE_STOCK, s.OM_BASE_STOCK)                          AS BASE_STOCK,
       s.APPAREL_INV,
       c.CATEGORY, m.IDEAL_CAT_MIX, c.DEPTH, c.CAT_INV, c.CAT_JIT, c.OPTIONS, c.CAT_L30,
       t.TARGET_MTD, t.TARGET_MONTH, a.ACTUAL_MTD,
       d.D_INV, d.D_JIT, d.D_IST_IN, d.D_IST_OUT, d.D_ROS7, d.D_LEAD, d.D_OUTWARD, d.D_CAT_BASE,
       ds.S_BASE, ds.S_INV, ds.S_NET_JIT, ds.S_NET_IST,
       pt.STORE_MONTH_TARGET, pt.CAT_TARGET_WEIGHT, pt.CAT_TARGET AS CAT_TARGET_MONTH,
       pt.CAT_TARGET * DAY(DATEADD(DAY, -1, CURRENT_DATE())) / DAY(LAST_DAY(DATEADD(DAY, -1, CURRENT_DATE()))) AS CAT_TARGET_MTD,
       pt.CAT_TARGET * pt.CAT_TARGET_PCT / 100                           AS CAT_REVENUE_MTD,
       IFF(s.STATE IN ('KARNATAKA', 'DELHI', 'HARYANA'), 60, 90)        AS MAX_DOI
FROM store s
JOIN cat c         ON c.bc = s.bc
LEFT JOIN mix m    ON m.bc = s.bc AND m.CATEGORY = c.CATEGORY
LEFT JOIN zone z   ON z.bc = s.bc
LEFT JOIN city c2  ON c2.bc = s.bc
LEFT JOIN tgt t    ON t.bc = s.bc
LEFT JOIN scd d   ON d.bc = s.bc AND d.CATEGORY = c.CATEGORY
LEFT JOIN scd_store ds ON ds.bc = s.bc
LEFT JOIN ptgt pt  ON pt.bc = s.bc AND pt.CATEGORY = c.CATEGORY
LEFT JOIN act a    ON a.bc = s.bc
