"""Central constants: Snowflake exclusions, category normalisation, scope, scoring weights.

Every SQL file in engine/sql/ is formatted with SQL_PARAMS, so an exclusion is changed in one place only.
"""
import os

# ---------------------------------------------------------------- connection (env / GitHub secrets)
SNOW_ACCOUNT = os.environ.get("SNOW_ACCOUNT") or "fs03183.ap-south-1.aws"
SNOW_USER = os.environ.get("SNOW_USER")
SNOW_WH = os.environ.get("SNOW_WH") or "SNITCH_WH"
SNOW_DB = os.environ.get("SNOW_DB") or "SNITCH_DB"
SNOW_SCHEMA = os.environ.get("SNOW_SCHEMA") or "MAPLEMONK"
SNOW_ROLE = os.environ.get("SNOW_ROLE")

CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
CF_KV_NAMESPACE_ID = os.environ.get("CF_KV_NAMESPACE_ID")
KV_KEY = "index.html"

OUTPUT_FILE = os.environ.get("TW_OUTPUT", "index.html")
CACHE_DIR = os.environ.get("TW_CACHE_DIR", ".cache")          # embedding cache (GitHub Release asset in CI)
EMBED_LIMIT = int(os.environ.get("TW_EMBED_LIMIT", "0"))      # >0 = only embed N new SKUs this run (testing)

# ---------------------------------------------------------------- scope
CATEGORIES = ["SHIRTS", "T-SHIRTS"]          # normalised names (see CATEGORY_CASE)
NEW_SKU_DAYS = 30                            # WH-live within N days and/or no offline sale yet -> "NEW"
NUDGE_DAYS = 21                              # WH inwards in the last N days shown in Nudges
FRESH_DAYS = 45                              # store stock first inwarded within N days counts as "fresh"

# ---------------------------------------------------------------- exclusions (DB brain)
EXCL_BRANCHES = "2,8,9,10,32,33,35,45,46,59,60,74,76,78,93,94"
EXCL_MARKETPLACES = ("'SNITCH - WH - EMIZA','SNITCH - WH - SR','SNITCH - WH - YELHANKA','SNITCH - WH - YELHANKA 2',"
                     "'SNITCH - MARKET PLACE - SLIKK','SNITCH - WH - B2B','SNITCH - WH - GUJARAT','SNITCH - WH - M P',"
                     "'SNITCH - WH - RAJASTHAN','SNITCH - WH - U.P','SNITCH - SNITCH X'")
EXCL_DOC_PREFIX = "'OMS','QCOM'"


def sku_excl(col):
    """SKU_GROUP / item-code exclusions (CB*, NT*, N0*, hangers, uniform, non-trading)."""
    return (f"UPPER({col}) NOT LIKE 'CB%' AND UPPER({col}) NOT LIKE 'NT%' AND UPPER({col}) NOT LIKE 'N0%' "
            f"AND UPPER({col}) NOT ILIKE '%HANGER%' AND UPPER({col}) <> 'UNIFORM' "
            f"AND UPPER({col}) NOT IN (SELECT DISTINCT UPPER(SKU_GROUP) FROM SNITCH_DB.MAPLEMONK.LOGIC_FINAL_ITEM_MASTER "
            f"WHERE CATEGORY ILIKE 'NON%TRADING%' AND SKU_GROUP IS NOT NULL)")


# Category from the SKU prefix (normalisation table). `b` = upper-cased SKU_GROUP.
CATEGORY_PREFIX_CASE = """
    CASE
      WHEN b REGEXP '^4MBL.*'                                     THEN 'BELTS'
      WHEN b REGEXP '^4MBG.*'                                     THEN 'PLUS TOPWEAR'
      WHEN b REGEXP '^4MTL.*'                                     THEN 'LUGGAGE'
      WHEN b REGEXP '^4(SWT|LSWT|BSWT).*'                         THEN 'SWEATSHIRTS'
      WHEN b REGEXP '^4(MSS|MSN|SHS|LSHS|BSHS|SFS|LSFS|BSFS).*'   THEN 'SHIRTS'
      WHEN b REGEXP '^4SHO.*'                                     THEN 'SHOES'
      WHEN b REGEXP '^4(MSH|SH|LSH|BSH).*'                        THEN 'SHORTS'
      WHEN b REGEXP '^4(MST|RN|LRN|BRN|PL|LPL|BPL).*'             THEN 'T-SHIRTS'
      WHEN b REGEXP '^4TRU.*'                                     THEN 'INNERWEAR'
      WHEN b REGEXP '^4(MSR|MTR|TR|LTR|BTR|CH|LCH|BCH).*'         THEN 'TROUSERS'
      WHEN b REGEXP '^4(MVK|MSD|JE|LJE|BJE).*'                    THEN 'JEANS'
      WHEN b REGEXP '^4(JK|LJK|BJK).*'                            THEN 'JACKETS'
      WHEN b REGEXP '^4(MSW|SW|LSW|BSW).*'                        THEN 'SWEATERS'
      WHEN b REGEXP '^4(HD|LHD|BHD).*'                            THEN 'HOODIES'
      WHEN b REGEXP '^4(OS|LOS|BOS).*'                            THEN 'OVERSHIRT'
      WHEN b REGEXP '^4(BL|LBL|BBL).*'                            THEN 'BLAZERS'
      WHEN b REGEXP '^4(CA|LCA|BCA).*'                            THEN 'CARGO PANTS'
      WHEN b REGEXP '^4(CD|LCD|BCD).*'                            THEN 'COORDS'
      WHEN b REGEXP '^4(MTP|JO|LJO|BJO).*'                        THEN 'JOGGERS & TRACKPANTS'
      WHEN b REGEXP '^4BX.*'                                      THEN 'BOXERS'
      WHEN b REGEXP '^4BR.*'                                      THEN 'INNERWEAR'
      WHEN b REGEXP '^(4BG|BP).*'                                 THEN 'BAGS'
      WHEN b REGEXP '^4(AC|MCP|MBD).*'                            THEN 'ACCESSORIES'
      WHEN b REGEXP '^(4SU|SN).*'                                 THEN 'SUNGLASSES'
      WHEN b REGEXP '^4BT.*'                                      THEN 'BELTS'
      WHEN b REGEXP '^4(MSFR|PR).*'                               THEN 'PERFUMES'
      WHEN b REGEXP '^4PY.*'                                      THEN 'PYJAMAS'
      ELSE NULL
    END"""


def category_synonym_case(col):
    """Free-text category (Shirt, Half Sleeve Shirt, Tshirt, Polo ...) -> normalised name; NULL if unknown."""
    c = f"REGEXP_REPLACE(UPPER(TRIM({col})), '[^A-Z]', '')"
    return f"""
    CASE
      WHEN {c} IN ('TSHIRT','TSHIRTS','ROUNDNECK','POLO','POLOS','POLOTSHIRT','POLOTSHIRTS') THEN 'T-SHIRTS'
      WHEN {c} IN ('OVERSHIRT','OVERSHIRTS')                                                THEN 'OVERSHIRT'
      WHEN {c} IN ('SWEATSHIRT','SWEATSHIRTS')                                              THEN 'SWEATSHIRTS'
      WHEN {c} IN ('SHIRT','SHIRTS','HALFSLEEVESHIRT','HALFSLEEVESHIRTS','HALFSLVSHIRT','HALFSLVSHIRTS',
                   'FULLSLEEVESHIRT','FULLSLEEVESHIRTS','FULLSLVSHIRT','FULLSLVSHIRTS')     THEN 'SHIRTS'
      ELSE NULL
    END"""


# Store ideal-mix buckets (same mapping as offline_metafield_ideal_mix.sql) - computed in SQL as DESIGN_BUCKET / COLLAR_BUCKET
TS_DESIGN_MAP = {"SOLID": "Solid", "GRAPHIC PRINT": "Graphic Print", "TEXTURED": "Self Design & Textured",
                 "SELF DESIGN": "Self Design & Textured", "STRIPES": "Stripes", "OTHERS": "Others",
                 "PRINTED": "Graphic Print", "EMBROIDED": "Embroided", "GEOMETRIC": "Graphic Print",
                 "CHECKS": "Checks", "FLORAL": "Graphic Print", "TIE & DYE": "Graphic Print",
                 "EMBELLISHED": "Embroided", "ANIMAL PRINT": "Graphic Print"}
SH_DESIGN_MAP = {"SOLID": "Solid", "STRIPES": "Stripes", "TEXTURED": "Self Design & Textured", "CHECKS": "Checks",
                 "SELF DESIGN": "Self Design & Textured", "PRINTED": "Printed", "OTHERS": "Others",
                 "FLORAL": "Printed", "EMBROIDED": "Embroided", "GEOMETRIC": "Printed", "TIE & DYE": "Printed",
                 "EMBELLISHED": "Embroided", "GRAPHIC PRINT": "Printed", "ANIMAL PRINT": "Printed"}
TS_COLLAR_MAP = {"POLO": "Polo", "ROUND": "Round", "V NECK": "Round", "CREW": "Round"}   # everything else -> Others


def design_bucket(category, designs, style):
    d = (designs or "").strip().upper()
    if category == "SHIRTS":
        s = (style or "").upper()
        if "LINEN" in s:
            return "Linen"
        if "LUXE" in s:
            return "Snitch LUXE"
        return SH_DESIGN_MAP.get(d, "Others")
    return TS_DESIGN_MAP.get(d, "Others")


def mix_key(category, collar, designs, style):
    """Key matching GS_T_SHIRTS_IDEAL_MIX (collar|designs) / GS_SHIRTS_IDEAL_MIX (designs)."""
    db = design_bucket(category, designs, style)
    if category == "T-SHIRTS":
        return TS_COLLAR_MAP.get((collar or "").strip().upper(), "Others") + " | " + db
    return db


# Price bands (MRP) used for store price-mix health
PRICE_BANDS = [(0, 999, "<1000"), (1000, 1499, "1000-1499"), (1500, 1999, "1500-1999"),
               (2000, 2499, "2000-2499"), (2500, 10 ** 9, "2500+")]


def price_band(mrp):
    for lo, hi, name in PRICE_BANDS:
        if lo <= (mrp or 0) <= hi:
            return name
    return "NA"


SIZES = ["XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL", "6XL"]

# ---------------------------------------------------------------- similarity (filtering_logic.md, FINAL)
SIM = {
    "top_k": 10,
    "keep": 20,                               # neighbours stored per SKU (top_k shown, rest feed demand)
    "tier_mult": {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4},
    "tier_tag": {1: "collar+fit+material", 2: "collar+fit", 3: "collar", 4: "category"},
    "soft_attrs": ["SLEEVE_TYPE", "CLOSURE", "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASSION_NEW", "FIT"],
    "soft_boost_damping": 0.20,
    "min_visual": 0.60,
    "calibration_percentile": 10.0,
    "default_floor": 0.40,
}
FIT_NORMALIZE = {"CROPPED OVERSIZED FIT": "Oversized", "BOX FIT": "Oversized", "OVERSIZED FIT": "Oversized",
                 "RELAXED FIT": "Oversized", "SLIM FIT": "Slim"}            # everything else -> Regular

# ---------------------------------------------------------------- demand + allocation
DEMAND = {"recency_half_life_days": 365,     # ~1-year half-life (settings.yaml decay_constant 12 months)
          "recency_floor": 0.2,              # very old neighbours still count a little
          "prior_weight": 3.0,               # shrinkage towards the neighbours' overall index (backtest-tuned)
          "own_weight": 3.0}                 # weight of an old SKU's own store ROS (at >= 30 days live)
DOI_CAP_STATES = {"KARNATAKA", "DELHI", "HARYANA"}  # WH states: 60 days cap, else 90 (as longtail SQL)
ALLOC_DEFAULT_WEIGHTS = {"ros": 0.30, "str": 0.15, "mix_gap": 0.15, "option_gap": 0.10,
                         "fill_gap": 0.10, "fresh_need": 0.05, "target_gap": 0.05, "colour_gap": 0.05,
                         "price_gap": 0.05}
ALLOC = {"days_cover": 30, "min_pack": 4, "max_per_store": 24,   # units per store-SKU
         "fill_ceiling": 140}       # % of base stock x ideal category mix; network median fill is ~130% today


SQL_PARAMS = {
    "EXCL_BRANCHES": EXCL_BRANCHES,
    "EXCL_MARKETPLACES": EXCL_MARKETPLACES,
    "EXCL_DOC_PREFIX": EXCL_DOC_PREFIX,
    "CATEGORY_PREFIX_CASE": CATEGORY_PREFIX_CASE,
    "CATS": ",".join("'%s'" % c for c in CATEGORIES),
    "OM_SKU_EXCL": sku_excl("om.SKU_GROUP"),
    "SKU_EXCL": sku_excl("SKU_GROUP"),
    "MD_CAT_SYN": category_synonym_case("md.CATEGORY"),
    "OM_CAT_SYN": category_synonym_case("om.NEW_CATEGORY"),
    "NUDGE_DAYS": NUDGE_DAYS,
}
