# state.py
import asyncio, base64

from construct import Struct, Int8ul, Int16ul, Int32ul, Int64ul, Bytes, Array

from solana.rpc.commitment import Processed, Confirmed

from solders.pubkey import Pubkey # type: ignore
from solana.rpc.async_api import AsyncClient

def le_bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, "little")

PUBKEY = Bytes(32)
U128   = Bytes(16)
MAX_CURVE_POINT_CONFIG = 20 # from constants.rs

BaseFeeLayout = Struct(
    "cliff_fee_num" / Int64ul,
    "second_factor" / Int64ul,
    "third_factor"  / Int64ul,
    "first_factor"  / Int16ul,
    "base_fee_mode" / Int8ul,
    "_pad0"         / Bytes(5),
)

DynamicFeeLayout = Struct(
    "initialized"               / Int8ul,
    "_pad"                      / Bytes(7),
    "max_volatility_acc"        / Int32ul,
    "variable_fee_control"      / Int32ul,
    "bin_step"                  / Int16ul,
    "filter_period"             / Int16ul,
    "decay_period"              / Int16ul,
    "reduction_factor"          / Int16ul,
    "_pad2"                     / Bytes(8),
    "bin_step_u128"             / U128,
)

PoolFeesLayout = Struct(
    "base_fee"          / BaseFeeLayout,
    "dynamic_fee"       / DynamicFeeLayout,
    "_pad0"             / Array(5, Int64ul),
    "_pad1"             / Bytes(6),
    "protocol_fee_pct"  / Int8ul,
    "referral_fee_pct"  / Int8ul,
)

LockedVestingLayout = Struct(
    "amount_per_period"                  / Int64ul,
    "cliff_duration_from_migration_time" / Int64ul,
    "frequency"                          / Int64ul,
    "number_of_period"                   / Int64ul,
    "cliff_unlock_amount"                / Int64ul,
    "_pad"                               / Int64ul,
)

LiquidityDistributionLayout = Struct(
    "sqrt_price" / U128,
    "liquidity"  / U128,
)

PoolConfigLayout = Struct(
    "quote_mint"            / PUBKEY,
    "fee_claimer"           / PUBKEY,
    "leftover_receiver"     / PUBKEY,
    "pool_fees"             / PoolFeesLayout,
    "collect_fee_mode"      / Int8ul,
    "migration_option"      / Int8ul,
    "activation_type"       / Int8ul,
    "token_decimal"         / Int8ul,
    "version"               / Int8ul,
    "token_type"            / Int8ul,
    "quote_token_flag"      / Int8ul,
    "partner_locked_lp_pct" / Int8ul,
    "partner_lp_pct"        / Int8ul,
    "creator_locked_lp_pct" / Int8ul,
    "creator_lp_pct"        / Int8ul,
    "migration_fee_option"  / Int8ul,
    "fixed_token_supply"    / Int8ul,
    "creator_trading_fee"   / Int8ul,
    "token_update_auth"     / Int8ul,
    "migration_fee_pct"     / Int8ul,
    "creator_mig_fee_pct"   / Int8ul,
    "_pad1"                 / Bytes(7),
    "swap_base_amount"          / Int64ul,
    "migration_quote_threshold" / Int64ul,
    "migration_base_threshold"  / Int64ul,
    "migration_sqrt_price"      / U128,
    "locked_vesting"            / LockedVestingLayout,
    "pre_mig_supply"            / Int64ul,
    "post_mig_supply"           / Int64ul,
    "_pad2"                     / Bytes(32),
    "sqrt_start_price"          / U128,
    "curve"                     / Array(MAX_CURVE_POINT_CONFIG, LiquidityDistributionLayout),
)

VirtualPoolLayout = Struct(
    "volatility_tracker" / Bytes(64),
    "config"             / PUBKEY,
    "creator"            / PUBKEY,
    "base_mint"          / PUBKEY,
    "base_vault"         / PUBKEY,
    "quote_vault"        / PUBKEY,
    "base_reserve"       / Int64ul,
    "quote_reserve"      / Int64ul,
    "protocol_base_fee"  / Int64ul,
    "protocol_quote_fee" / Int64ul,
    "partner_base_fee"   / Int64ul,
    "partner_quote_fee"  / Int64ul,
    "sqrt_price_raw"     / Bytes(16),
    "activation_point"   / Int64ul,
    "pool_type"          / Int8ul,
    "is_migrated"        / Int8ul,
    "is_partner_withdraw_surplus"  / Int8ul,
    "is_protocol_withdraw_surplus" / Int8ul,
    "migration_progress"          / Int8ul,
    "is_withdraw_leftover"        / Int8ul,
    "is_creator_withdraw_surplus" / Int8ul,
    "padding0"           / Int8ul,
    "metrics"            / Bytes(32),
    "finish_curve_timestamp" / Int64ul,
    "creator_base_fee"   / Int64ul,
    "creator_quote_fee"  / Int64ul,
    "padding1"           / Bytes(56),
)

Q64 = 1 << 64
def price_from_sqrt(sqrt_q64: int, base_dec: int, quote_dec: int) -> float:
    p = (sqrt_q64 / Q64) ** 2
    if quote_dec != base_dec:
        p *= 10 ** (quote_dec - base_dec)
    return p

def migration_quote_amount(threshold: int, fee_pct: int) -> tuple[int,int]:
    """
        Returns (quote_amount_without_fee, fee_amount)
    """
    quote_amt = (threshold * 100 + (100 - fee_pct) - 1) // (100 - fee_pct)  # ceil div
    fee       = threshold - quote_amt
    return quote_amt, fee

async def fetch_virtual_pool(pool_addr: str, ctx: AsyncClient):
    pk = Pubkey.from_string(pool_addr)
    acc = (await ctx.get_account_info(pk, encoding="base64", commitment=Processed)).value
    if acc is None:
        raise RuntimeError(f"account not found {pool_addr}")

    if isinstance(acc.data, bytes):
        blob = acc.data
    elif isinstance(acc.data, tuple):
        blob = base64.b64decode(acc.data[0])
    else:
        raise TypeError(f"unexpected data field type: {type(acc.data)}")

    blob = blob[8:]
    parsed = VirtualPoolLayout.parse(blob)

    def b58(x: bytes) -> str:
        return str(Pubkey.from_bytes(x))

    out = {}
    for k, v in parsed.items():
        if k == "sqrt_price_raw":
            out["sqrt_price"] = int.from_bytes(v, "little")
        elif isinstance(v, bytes) and len(v) == 32:
            out[k] = b58(v)
        else:
            out[k] = v
    return out

async def fetch_pool_config(pool_addr: str, ctx: AsyncClient):
    pk   = Pubkey.from_string(pool_addr)
    acc  = (await ctx.get_account_info(pk, encoding="base64", commitment=Confirmed)).value
    if acc is None:
        raise RuntimeError(f"PoolConfig account {pool_addr} not found")

    blob = base64.b64decode(acc.data[0]) if isinstance(acc.data, tuple) else acc.data
    parsed = PoolConfigLayout.parse(blob[8:])

    def to_pubkey(b):  return str(Pubkey.from_bytes(b))
    def u128(b):       return int.from_bytes(b, "little")

    cfg = {
        "quote_mint"                : to_pubkey(parsed.quote_mint),
        "fee_claimer"               : to_pubkey(parsed.fee_claimer),
        "leftover_receiver"         : to_pubkey(parsed.leftover_receiver),
        "migration_quote_threshold" : parsed.migration_quote_threshold,
        "migration_base_threshold"  : parsed.migration_base_threshold,
        "migration_fee_pct"         : parsed.migration_fee_pct,
        "migration_sqrt_price"      : u128(parsed.migration_sqrt_price),
        "sqrt_start_price"          : u128(parsed.sqrt_start_price),
    }
    return cfg