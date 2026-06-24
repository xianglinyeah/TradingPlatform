"""Field definitions for the 8 fundamentals tables.

Direct translation of C# `FundamentalsFieldConfig` + `FundamentalsCatalog`.
GM SDK limits each API call to ≤20 fields; `batch()` chunks accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

MAX_FIELDS_PER_CALL = 20


class TableKind(str, Enum):
    Quarterly = "quarterly"
    Daily = "daily"


class FundApiMethod(str, Enum):
    Balance = "balance"
    Cashflow = "cashflow"
    Income = "income"
    Prime = "prime"
    Deriv = "deriv"
    Valuation = "valuation"
    Mktvalue = "mktvalue"
    Basic = "basic"


# ----------------------------- Quarterly -----------------------------

BALANCE = [
    "mny_cptl", "acct_rcv", "invt", "ppay", "oth_rcv", "note_acct_rcv", "ttl_cur_ast",
    "fix_ast", "intg_ast", "gw", "lt_eqy_inv", "cred_inv", "dfr_tax_ast", "ttl_ncur_ast",
    "sht_ln", "acct_pay", "note_acct_pay", "emp_comp_pay", "tax_pay", "ttl_cur_liab",
    "lt_ln", "bnd_pay", "dfr_tax_liab", "ttl_ncur_liab",
    "paid_in_cptl",
]
BALANCE_EXTRA = [
    "cptl_rsv", "sur_rsv", "ret_prof", "ttl_eqy_pcom", "ttl_eqy", "ttl_ast", "ttl_liab",
    "ttl_liab_eqy",
]
CASHFLOW = [
    "net_cf_oper", "cash_rcv_sale", "cash_pur_gds_svc", "cash_pay_emp", "cash_pay_tax",
    "cf_in_oper", "cf_out_oper",
    "cash_rcv_sale_inv", "cash_pay_inv", "pur_fix_intg_ast", "net_cf_inv",
    "brw_rcv", "cash_rpay_brw", "cash_pay_dvd_int", "net_cf_fin",
    "cf_in_fin", "cf_out_fin", "net_incr_cash_eq",
]
INCOME = [
    "ttl_inc_oper", "inc_oper",
    "ttl_cost_oper", "cost_oper", "biz_tax_sur", "exp_sell", "exp_adm", "exp_rd",
    "exp_fin", "int_fee", "inc_int",
    "inc_inv", "inc_ast_dspl", "ast_impr_loss", "cred_impr_loss", "inc_fv_chg", "inc_other",
    "oper_prof", "inc_noper", "exp_noper", "ttl_prof", "inc_tax", "net_prof",
    "net_prof_pcom", "min_int_inc",
    "eps_base", "eps_dil",
]
PRIME = [
    "eps_basic", "eps_dil", "eps_basic_cut", "eps_dil_cut", "bps_pcom_ps", "net_cf_oper_ps",
    "ttl_ast", "ttl_liab", "ttl_eqy_pcom", "net_prof_pcom",
    "roe", "roe_weight_avg", "roe_cut", "roe_weight_avg_cut",
    "net_prof_pcom_yoy", "inc_oper_yoy",
]
DERIV = [
    "roe", "roe_weight", "roe_avg", "roe_cut", "roa", "roa_ann", "jroa", "roic",
    "sale_npm", "sale_gpm", "net_prof_toi", "oper_prof_toi",
    "eps_basic", "eps_dil2", "bps", "ebit", "ebitda", "ebit_inverse", "ebitda_inverse",
    "gross_prof",
    "ttl_inv_cptl", "work_cptl", "net_work_cptl", "int_debt", "net_debt",
    "fcff", "fcfe", "fcff_ps", "fcfe_ps", "ebitda_ps",
    "ast_liab_rate", "curr_rate", "quick_rate", "liab_eqy_rate",
    "inv_turnover_days", "acct_rcv_turnover_days", "oper_cycle", "ttl_ast_turnover_rate",
    "ttl_inc_oper_yoy", "net_prof_pcom_yoy",
]
DERIV_EXTRA = ["net_prof_yoy", "eps_dil_yoy"]

# ----------------------------- Daily -----------------------------

VALUATION = [
    "pe_ttm", "pe_lyr", "pe_mrq", "pe_ttm_cut",
    "pb_lyr", "pb_mrq",
    "pcf_ttm_oper", "pcf_ttm_ncf",
    "ps_ttm", "ps_lyr", "ps_mrq",
    "peg_lyr", "peg_1q", "peg_2q", "peg_3q",
    "dy_ttm", "dy_lfy",
]
MKTVALUE = [
    "tot_mv", "tot_mv_csrc", "a_mv", "a_mv_ex_ltd", "b_mv", "b_mv_ex_ltd",
    "ev", "ev_ex_curr", "ev_ebitda", "equity_value",
]
BASIC = [
    "tclose", "turnrate", "ttl_shr", "circ_shr", "ttl_shr_unl", "ttl_shr_ltd",
    "a_shr_unl", "h_shr_unl",
]


def _concat(*arrays) -> List[str]:
    out: List[str] = []
    for a in arrays:
        out.extend(a)
    return out


def batch(fields: List[str], size: int = MAX_FIELDS_PER_CALL) -> List[List[str]]:
    return [fields[i:i + size] for i in range(0, len(fields), size)]


@dataclass(frozen=True)
class FundTableSpec:
    table_name: str
    kind: TableKind
    fields: tuple
    has_rpt_type_params: bool
    returns_rpt_type: bool
    method: FundApiMethod


def _spec(table_name, kind, fields_list, has_rpt, returns_rpt, method):
    return FundTableSpec(
        table_name=table_name,
        kind=kind,
        fields=tuple(fields_list),
        has_rpt_type_params=has_rpt,
        returns_rpt_type=returns_rpt,
        method=method,
    )


TABLES: List[FundTableSpec] = [
    _spec("balance_sheet", TableKind.Quarterly,
          _concat(BALANCE, BALANCE_EXTRA), True, False, FundApiMethod.Balance),
    _spec("cashflow_statement", TableKind.Quarterly,
          CASHFLOW, True, False, FundApiMethod.Cashflow),
    _spec("income_statement", TableKind.Quarterly,
          INCOME, True, False, FundApiMethod.Income),
    _spec("finance_prime", TableKind.Quarterly,
          PRIME, True, True, FundApiMethod.Prime),
    _spec("finance_deriv", TableKind.Quarterly,
          _concat(DERIV, DERIV_EXTRA), True, True, FundApiMethod.Deriv),
    _spec("daily_valuation", TableKind.Daily,
          VALUATION, False, False, FundApiMethod.Valuation),
    _spec("daily_mktvalue", TableKind.Daily,
          MKTVALUE, False, False, FundApiMethod.Mktvalue),
    _spec("daily_basic", TableKind.Daily,
          BASIC, False, False, FundApiMethod.Basic),
]


# Preflight safety thresholds (mirrors C# PreflightMinCounts).
PREFLIGHT_MIN_COUNTS = {
    "balance_sheet": 50_000,
    "cashflow_statement": 50_000,
    "income_statement": 50_000,
    "finance_prime": 200_000,
    "finance_deriv": 200_000,
    "daily_valuation": 1_000_000,
    "daily_mktvalue": 1_000_000,
    "daily_basic": 1_000_000,
}
