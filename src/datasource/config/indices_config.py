#!/usr/bin/env python3
"""
统一指数配置管理
集中管理所有金融数据的代码映射和配置
"""

# A股主要指数配置
A_SHARE_INDICES = {
    "上证指数": {
        "symbol": "000001",
        "display_name": "上证指数(000001)",
        "category": "综合指数",
        "market": "上海"
    },
    "深证成指": {
        "symbol": "399001", 
        "display_name": "深证成指(399001)",
        "category": "综合指数",
        "market": "深圳"
    },
    "创业板指": {
        "symbol": "399006",
        "display_name": "创业板指(399006)", 
        "category": "板块指数",
        "market": "深圳"
    },
    "沪深300": {
        "symbol": "000300",
        "display_name": "沪深300(000300)",
        "category": "规模指数", 
        "market": "沪深"
    },
    "上证50": {
        "symbol": "000016",
        "display_name": "上证50(000016)",
        "category": "蓝筹指数",
        "market": "上海"
    },
    "中证500": {
        "symbol": "000905", 
        "display_name": "中证500(000905)",
        "category": "中盘指数",
        "market": "沪深"
    },
    "科创50": {
        "symbol": "000688",
        "display_name": "科创50(000688)",
        "category": "板块指数", 
        "market": "上海"
    }
}

# 美股主要指数配置
US_INDICES = {
    "标普500": {
        "symbol": "SPX",
        "display_name": "标普500(SPX)",
        "category": "综合指数",
        "market": "美国"
    },
    "纳斯达克": {
        "symbol": "IXIC", 
        "display_name": "纳斯达克综指(IXIC)",
        "category": "科技指数",
        "market": "美国"
    },
    "道琼斯": {
        "symbol": "DJI",
        "display_name": "道琼斯指数(DJI)",
        "category": "蓝筹指数", 
        "market": "美国"
    },
    "罗素2000": {
        "symbol": "RUT",
        "display_name": "罗素2000(RUT)",
        "category": "小盘指数",
        "market": "美国"
    },
    "费城半导体": {
        "symbol": "SOX", 
        "display_name": "费城半导体(SOX)",
        "category": "行业指数",
        "market": "美国"
    }
}

# 港股主要指数配置
HK_INDICES = {
    "恒生指数": {
        "symbol": "HSI",
        "display_name": "恒生指数(HSI)",
        "category": "综合指数",
        "market": "香港"
    },
    "恒生科技": {
        "symbol": "HSTECH",
        "display_name": "恒生科技(HSTECH)", 
        "category": "科技指数",
        "market": "香港"
    }
}

# 债券ETF配置
BOND_ETFS = {
    "国债ETF": {
        "symbol": "511010",
        "display_name": "5年期国债ETF(511010)",
        "category": "国债",
        "duration": "5年"
    },
    "十年国债": {
        "symbol": "019649",
        "display_name": "十年期国债(019649)",
        "category": "国债",
        "duration": "10年"
    },
    "国开债": {
        "symbol": "019950",
        "display_name": "国开债(019950)",
        "category": "政策性金融债",
        "duration": "10年"
    }
}

# 国债收益率配置 - 120背景扫描方案完整覆盖
BOND_YIELDS = {
    "美国10年期": {
        "symbol": "US10Y",
        "display_name": "美国10年期国债收益率",
        "country": "美国",
        "duration": "10年",
        "data_source": "FRED数据",
        "yahoo_symbol": "^TNX",
        "priority": 1,
        "alternative_symbols": ["^TNX", "US10Y"]
    },
    "中国10年期": {
        "symbol": "CN10Y",
        "display_name": "中国10年期国债收益率",
        "country": "中国",
        "duration": "10年",
        "data_source": "中债估值",
        "proxy_etf": "511010",
        "priority": 1,
        "alternative_symbols": ["511010", "019649"]
    },
    "中国10年国开": {
        "symbol": "CN10Y_CDB",
        "display_name": "中国10年期国开债收益率",
        "country": "中国",
        "duration": "10年",
        "data_source": "中债AAA代理",
        "proxy_etf": "019950",
        "priority": 2,
        "alternative_symbols": ["019950"]
    },
    "德国10年期": {
        "symbol": "DE10Y",
        "display_name": "德国10年期国债收益率",
        "country": "德国",
        "duration": "10年",
        "data_source": "外部数据",
        "yahoo_symbol": "^TNX-DE",
        "priority": 3
    },
    "日本10年期": {
        "symbol": "JP10Y",
        "display_name": "日本10年期国债收益率",
        "country": "日本",
        "duration": "10年",
        "data_source": "外部数据",
        "yahoo_symbol": "^TNX-JP",
        "priority": 3
    }
}

# 商品期货配置 - V2.1 国际期货增强
COMMODITY_FUTURES = {
    # 国际商品期货（优先使用）
    "COMEX黄金": {
        "symbol": "GC",
        "display_name": "COMEX黄金期货",
        "category": "贵金属",
        "unit": "美元/盎司",
        "exchange": "COMEX",
        "data_source": "yahoo_finance",
        "yahoo_symbol": "GC=F",
        "websearch_keywords": "COMEX黄金期货 金价",
        "priority": 1
    },
    "WTI原油": {
        "symbol": "CL",
        "display_name": "WTI原油期货",
        "category": "能源",
        "unit": "美元/桶",
        "exchange": "NYMEX",
        "data_source": "yahoo_finance",
        "yahoo_symbol": "CL=F",
        "websearch_keywords": "WTI原油价格 crude oil",
        "priority": 1
    },
    "Brent原油": {
        "symbol": "BZ",
        "display_name": "Brent布伦特原油",
        "category": "能源",
        "unit": "美元/桶",
        "exchange": "ICE",
        "data_source": "yahoo_finance",
        "yahoo_symbol": "BZ=F",
        "websearch_keywords": "Brent原油 布伦特",
        "priority": 1
    },
    "COMEX铜": {
        "symbol": "HG",
        "display_name": "COMEX铜期货",
        "category": "工业金属",
        "unit": "美元/磅",
        "exchange": "COMEX",
        "data_source": "yahoo_finance",
        "yahoo_symbol": "HG=F",
        "websearch_keywords": "COMEX铜期货 铜价",
        "priority": 1
    },
    "BCOM指数": {
        "symbol": "BCOM",
        "display_name": "Bloomberg商品指数",
        "category": "商品指数",
        "unit": "指数点",
        "exchange": "Bloomberg",
        "data_source": "websearch",
        "websearch_keywords": "Bloomberg Commodity Index BCOM",
        "priority": 1
    },
    "GSG商品ETF": {
        "symbol": "GSG",
        "display_name": "iShares S&P GSCI商品ETF",
        "category": "商品指数",
        "unit": "美元",
        "exchange": "NYSE",
        "data_source": "yahoo_finance",
        "yahoo_symbol": "GSG",
        "websearch_keywords": "GSG ETF S&P GSCI",
        "priority": 1,
        "description": "追踪S&P GSCI指数，能源占比近70%"
    },
    # 国内商品期货（备用）
    "黄金主力": {
        "symbol": "AU0",
        "display_name": "黄金主力(AU0)",
        "category": "贵金属",
        "unit": "元/克",
        "exchange": "上期所",
        "priority": 2
    },
    "原油主力": {
        "symbol": "SC0",
        "display_name": "原油主力(SC0)",
        "category": "能源",
        "unit": "元/桶",
        "exchange": "上期所",
        "priority": 2
    },
    "铜主力": {
        "symbol": "CU0",
        "display_name": "铜主力(CU0)",
        "category": "工业金属",
        "unit": "元/吨",
        "exchange": "上期所",
        "priority": 2
    }
}

# 汇率配置 - 120背景扫描方案完整覆盖
FOREX_PAIRS = {
    "美元指数": {
        "symbol": "DXY",
        "display_name": "美元指数(DXY)",
        "base": "USD",
        "quote": "综合",
        "data_source": "外汇数据",
        "yahoo_symbol": "DX-Y.NYB",
        "priority": 1
    },
    "美元人民币": {
        "symbol": "USDCNY",
        "display_name": "USD/CNY在岸",
        "base": "USD",
        "quote": "CNY",
        "data_source": "SAFE数据",
        "yahoo_symbol": "USDCNY=X",
        "priority": 1
    },
    "美元离岸人民币": {
        "symbol": "USDCNH",
        "display_name": "USD/CNH离岸",
        "base": "USD",
        "quote": "CNH",
        "data_source": "CFETS数据",
        "yahoo_symbol": "USDCNH=X",
        "priority": 1
    },
    "欧元美元": {
        "symbol": "EURUSD",
        "display_name": "EUR/USD",
        "base": "EUR",
        "quote": "USD",
        "data_source": "外汇数据",
        "yahoo_symbol": "EURUSD=X",
        "priority": 2
    },
    "英镑美元": {
        "symbol": "GBPUSD",
        "display_name": "GBP/USD",
        "base": "GBP",
        "quote": "USD",
        "data_source": "外汇数据",
        "yahoo_symbol": "GBPUSD=X",
        "priority": 2
    },
    "日元美元": {
        "symbol": "USDJPY",
        "display_name": "USD/JPY",
        "base": "USD",
        "quote": "JPY",
        "data_source": "外汇数据",
        "yahoo_symbol": "USDJPY=X",
        "priority": 2
    }
}

# TuShare数据接口配置
TUSHARE_API_CONFIG = {
    # 基础数据接口
    "basic_data": {
        "stock_basic": {
            "name": "股票列表",
            "fields": "ts_code,symbol,name,area,industry,market,list_date",
            "description": "获取基础信息数据，包括股票代码、名称、上市日期等"
        },
        "new_share": {
            "name": "IPO新股上市",
            "fields": "ts_code,sub_code,name,ipo_date,issue_date,amount,market_amount,price,pe,limit_amount,funds,ballot",
            "description": "获取新股上市列表数据"
        },
        "trade_cal": {
            "name": "交易日历",
            "fields": "exchange,cal_date,is_open,pretrade_date",
            "description": "获取各大交易所交易日历数据"
        },
        "name_change": {
            "name": "股票曾用名",
            "fields": "ts_code,name,start_date,end_date,ann_date,change_reason",
            "description": "历史名称变更记录"
        },
        "hs_const": {
            "name": "沪深港通成分股",
            "fields": "ts_code,hs_type,in_date,out_date,is_new",
            "description": "获取沪深港通成分股数据"
        },
        "stk_managers": {
            "name": "上市公司管理层",
            "fields": "ts_code,ann_date,name,gender,lev,title,edu,national,birthday,begin_date,end_date,resume",
            "description": "上市公司管理层名单及个人信息"
        }
    },

    # 行情数据接口
    "market_data": {
        "daily": {
            "name": "日线行情",
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            "description": "获取股票日线数据"
        },
        "weekly": {
            "name": "周线行情",
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            "description": "获取股票周线数据"
        },
        "monthly": {
            "name": "月线行情",
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            "description": "获取股票月线数据"
        },
        "adj_factor": {
            "name": "复权因子",
            "fields": "ts_code,trade_date,adj_factor",
            "description": "获取股票复权因子"
        },
        "daily_basic": {
            "name": "每日指标",
            "fields": "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv",
            "description": "获取全部股票每日重要的基本面指标"
        },
        "pro_bar": {
            "name": "通用行情接口",
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            "description": "目前整合了股票（未复权、前复权、后复权）、指数、数字货币的行情数据"
        },
        "stk_limit": {
            "name": "涨跌停价格",
            "fields": "ts_code,trade_date,up_limit,down_limit",
            "description": "获取全市场（包含A/B股和基金）每日涨跌停价格"
        }
    },

    # 财务数据接口
    "financial_data": {
        "income": {
            "name": "利润表",
            "fields": "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,basic_eps,diluted_eps,total_revenue,revenue,int_income,prem_earned,comm_income,n_commis_income,n_oth_income,n_oth_b_income,prem_income,out_prem,une_prem_reser,reins_income,n_sec_tb_income,n_sec_uw_income,n_asset_mg_income,oth_b_income,fv_value_chg_gain,invest_income,ass_invest_income,forex_gain,total_cogs,oper_cost,int_exp,comm_exp,biz_tax_surchg,sell_exp,admin_exp,fin_exp,assets_impair_loss,prem_refund,compens_payout,reser_insur_liab,div_payt,reins_exp,oper_exp,compens_payout_refu,insur_reser_refu,reins_cost_refund,other_bus_cost,operate_profit,non_oper_income,non_oper_exp,nca_disploss,total_profit,income_tax,n_income,n_income_attr_p,minority_gain,oth_compr_income,t_compr_income,compr_inc_attr_p,compr_inc_attr_m_s,ebit,ebitda,insurance_exp,undist_profit,distable_profit",
            "description": "获取上市公司财务利润表数据"
        },
        "balancesheet": {
            "name": "资产负债表",
            "fields": "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,total_share,cap_rese,undistr_porfit,surplus_rese,special_rese,money_cap,trad_asset,notes_receiv,accounts_receiv,oth_receiv,prepayment,div_receiv,int_receiv,inventories,amor_exp,nca_within_1y,sett_rsrv,loanto_oth_bank_fi,premium_receiv,reinsur_receiv,reinsur_res_receiv,pur_resale_fa,oth_cur_assets,total_cur_assets,fa_avail_for_sale,htm_invest,lt_eqt_invest,invest_real_estate,time_deposits,oth_assets,lt_rec,fix_assets,cip,const_materials,fixed_assets_disp,produc_bio_assets,oil_and_gas_assets,intan_assets,r_and_d,goodwill,lt_amor_exp,defer_tax_assets,decr_in_disbur,oth_nca,total_nca,cash_reser_cb,depos_in_oth_bfi,prec_metals,deriv_assets,rr_reins_une_prem,rr_reins_outstd_cla,rr_reins_lins_liab,rr_reins_lthins_liab,refund_depos,ph_pledge_loans,refund_cap_depos,indep_acct_assets,client_depos,client_prov,transac_seat_fee,invest_as_receiv,total_assets,st_borr,cb_borr,depos_ib_deposits,loan_oth_bank,trading_fl,notes_payable,acct_payable,adv_receipts,sold_for_repur_fa,comm_payable,payroll_payable,taxes_payable,int_payable,div_payable,oth_payable,acc_exp,deferred_inc,st_bonds_payable,payable_to_reinsurer,rsrv_insur_cont,acting_trading_sec,acting_uw_sec,non_cur_liab_due_1y,oth_cur_liab,total_cur_liab,bond_payable,lt_payable,specific_payables,estimated_liab,defer_tax_liab,defer_inc_non_cur_liab,oth_ncl,total_ncl,depos_oth_bfi,deriv_liab,depos,agency_bus_liab,oth_liab,prem_receiv_adva,depos_received,ph_invest,reser_une_prem,reser_outstd_claims,reser_lins_liab,reser_lthins_liab,indept_acc_liab,pledge_borr,indem_payable,policy_div_payable,total_liab,treasury_share,ordin_risk_reser,forex_differ,invest_loss_unconf,minority_int,total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int,total_liab_hldr_eqy,lt_payroll_payable,oth_comp_income,oth_eqt_tools,oth_eqt_tools_p_shr,lending_funds,acc_receivable,st_fin_payable,payables,hfs_assets,hfs_sales",
            "description": "获取上市公司资产负债表"
        },
        "cashflow": {
            "name": "现金流量表",
            "fields": "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,net_profit,finan_exp,c_fr_sale_sg,recp_tax_rends,n_depos_incr_fi,n_incr_loans_cb,n_inc_borr_oth_fi,prem_fr_orig_contr,n_incr_insured_dep,n_reinsur_prem,n_incr_disp_tfa,ifc_cash_incr,n_incr_disp_faas,n_incr_loans_oth_bank,n_cap_incr_repur,c_fr_oth_operate_a,c_inf_fr_operate_a,c_paid_goods_s,c_paid_to_for_empl,c_paid_for_taxes,n_decr_insured_dep,n_decr_loans_cb,c_paid_for_oth_operate_a,c_outf_fr_operate_a,n_cashflow_act,oth_recp_ral_inv_act,c_disp_withdrwl_invest,c_recp_return_invest,n_recp_disp_fiolta,n_recp_disp_sobu,stot_inflows_inv_act,c_pay_acq_const_fiolta,c_paid_invest,n_disp_subs_oth_biz,oth_pay_ral_inv_act,n_incr_pledge_loan,stot_out_inv_act,n_cashflow_inv_act,c_recp_borrow,proc_issue_bonds,oth_cash_recp_ral_fnc_act,stot_cash_in_fnc_act,free_cashflow,c_prepay_amt_borr,c_pay_dist_dpcp_int_exp,incl_dvd_profit_paid_sc_ms,oth_cashpay_ral_fnc_act,stot_cashout_fnc_act,n_cash_flows_fnc_act,eff_fx_flu_cash,n_incr_cash_cash_equ,c_cash_equ_beg_period,c_cash_equ_end_period,c_recp_cap_contrib,incl_cash_rec_saims,uncon_invest_loss,prov_depr_assets,depr_fa_coga_dpba,amort_intang_assets,lt_amort_deferred_exp,decr_deferred_exp,incr_acc_exp,loss_disp_fiolta,loss_scr_fa,loss_fv_chg,invest_loss,decr_def_inc_tax_assets,incr_def_inc_tax_liab,decr_inventories,decr_oper_payable,incr_oper_payable,others,im_net_cashflow_oper_act,conv_debt_into_cap,conv_copbonds_due_within_1y,fa_fnc_leases,end_bal_cash,beg_bal_cash,end_bal_cash_equ,beg_bal_cash_equ,im_n_incr_cash_equ",
            "description": "获取上市公司现金流量表"
        },
        "fina_indicator": {
            "name": "财务指标数据",
            "fields": "ts_code,ann_date,end_date,eps,dt_eps,total_revenue_ps,revenue_ps,capital_rese_ps,surplus_rese_ps,undist_profit_ps,extra_item,profit_dedt,gross_margin,current_ratio,quick_ratio,cash_ratio,invturn_days,arturn_days,inv_turn,ar_turn,ca_turn,fa_turn,assets_turn,op_income,valuechange_income,interst_income,daa,ebit,ebitda,fcff,fcfe,current_exint,noncurrent_exint,interestdebt,netdebt,tangible_asset,working_capital,networking_capital,invest_capital,retained_earnings,diluted2_eps,bps,ocfps,retainedps,cfps,ebit_ps,fcff_ps,fcfe_ps,netprofit_margin,grossprofit_margin,cogs_of_sales,expense_of_sales,profit_to_gr,saleexp_to_gr,adminexp_of_gr,finaexp_of_gr,impai_ttm,gc_of_gr,op_of_gr,ebit_of_gr,roe,roe_waa,roe_dt,roa,npta,roic,roe_yearly,roa_yearly,roe_avg,opincome_of_ebt,investincome_of_ebt,n_op_profit_of_ebt,tax_to_ebt,dtprofit_to_profit,salescash_to_or,ocf_to_or,ocf_to_opincome,capitalized_to_da,debt_to_assets,assets_to_eqt,dp_assets_to_eqt,ca_to_assets,nca_to_assets,tbassets_to_totalassets,int_to_talcap,eqt_to_talcapital,currentdebt_to_debt,longdeb_to_debt,ocf_to_shortdebt,debt_to_eqt,eqt_to_debt,eqt_to_interestdebt,tangibleasset_to_debt,tangasset_to_intdebt,tangibleasset_to_netdebt,ocf_to_debt,ocf_to_interestdebt,ocf_to_netdebt,ebit_to_interest,longdebt_to_workingcapital,ebitda_to_debt,turn_days,roa_yearly,roa_dp,fixed_assets,profit_prefin_exp,non_op_profit,op_to_ebt,nop_to_ebt,ocf_to_profit,cash_to_liqdebt,cash_to_liqdebt_withinterest,op_to_liqdebt,op_to_debt,roic_yearly,total_fa_trun,profit_to_op,q_opincome,q_investincome,q_dtprofit,q_eps,q_netprofit_margin,q_gsprofit_margin,q_exp_to_sales,q_profit_to_gr,q_saleexp_to_gr,q_adminexp_to_gr,q_finaexp_to_gr,q_impair_to_gr_ttm,q_gc_to_gr,q_op_to_gr,q_roe,q_dt_roe,q_npta,q_opincome_to_ebt,q_investincome_to_ebt,q_dtprofit_to_profit,q_salescash_to_or,q_ocf_to_sales,q_ocf_to_or,basic_eps_yoy,dt_eps_yoy,cfps_yoy,op_yoy,ebt_yoy,netprofit_yoy,dt_netprofit_yoy,ocf_yoy,roe_yoy,bps_yoy,assets_yoy,eqt_yoy,tr_yoy,or_yoy,q_gr_yoy,q_gr_qoq,q_sales_yoy,q_sales_qoq,q_op_yoy,q_op_qoq,q_profit_yoy,q_profit_qoq,q_netprofit_yoy,q_netprofit_qoq,equity_yoy,rd_exp,update_flag",
            "description": "获取上市公司财务指标数据"
        },
        "forecast": {
            "name": "业绩预告",
            "fields": "ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,net_profit_max,last_parent_net,first_ann_date,summary,change_reason",
            "description": "获取上市公司业绩预告数据"
        },
        "express": {
            "name": "业绩快报",
            "fields": "ts_code,ann_date,end_date,revenue,operate_profit,total_profit,n_income,total_assets,total_hldr_eqy_exc_min_int,diluted_eps,diluted_roe,yoy_net_profit,bps,yoy_sales,yoy_op,yoy_tp,yoy_dedu_np,yoy_eps,yoy_roe,growth_assets,yoy_equity,growth_bps,or_last_year,op_last_year,tp_last_year,np_last_year,eps_last_year,open_net_assets,open_bps,perf_summary,is_audit,remark",
            "description": "获取上市公司业绩快报"
        },
        "dividend": {
            "name": "分红送股数据",
            "fields": "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share",
            "description": "分红送股详情"
        },
        "top10_holders": {
            "name": "前十大股东",
            "fields": "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio",
            "description": "前十大股东数据"
        },
        "top10_floatholders": {
            "name": "前十大流通股东",
            "fields": "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio",
            "description": "前十大流通股东数据"
        }
    },

    # 指数数据接口
    "index_data": {
        "index_basic": {
            "name": "指数基本信息",
            "fields": "ts_code,name,fullname,market,publisher,index_type,category,base_date,base_point,list_date,weight_rule,desc,exp_date",
            "description": "获取指数基础信息"
        },
        "index_daily": {
            "name": "指数日线行情",
            "fields": "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount",
            "description": "获取指数每日行情"
        },
        "index_weight": {
            "name": "指数成分和权重",
            "fields": "index_code,con_code,trade_date,weight",
            "description": "获取各类指数成分和权重"
        },
        "index_daily_basic": {
            "name": "指数每日指标",
            "fields": "ts_code,trade_date,total_mv,float_mv,total_share,float_share,free_share,turnover_rate,turnover_rate_f,pe,pe_ttm,pb",
            "description": "获取指数每日指标数据"
        },
        "sz_daily_info": {
            "name": "深圳市场每日交易统计",
            "fields": "trade_date,ts_code,exchange,total_share,float_share,total_mv,float_mv,pe,turnover_rate",
            "description": "深圳证券交易所每日市场交易概况"
        }
    },

    # 资金流向数据接口
    "money_flow": {
        "moneyflow": {
            "name": "个股资金流向",
            "fields": "ts_code,trade_date,buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount,buy_md_vol,buy_md_amount,sell_md_vol,sell_md_amount,buy_lg_vol,buy_lg_amount,sell_lg_vol,sell_lg_amount,buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,net_mf_vol,net_mf_amount",
            "description": "获取沪深A股票资金流向数据"
        },
        "moneyflow_hsgt": {
            "name": "沪深港通资金流向",
            "fields": "trade_date,ggt_ss,ggt_sz,hgt,sgt,north_money,south_money",
            "description": "获取沪深港通每日资金流向数据"
        },
        "hsgt_top10": {
            "name": "港股通十大成交股",
            "fields": "trade_date,ts_code,name,close,change,rank,market_type,amount,net_amount,buy,sell",
            "description": "获取港股通每日成交数据"
        },
        "ggt_top10": {
            "name": "港股通十大成交股",
            "fields": "trade_date,ts_code,name,close,change,rank,market_type,amount,net_amount,buy,sell",
            "description": "获取港股通每日成交数据"
        }
    },

    # 行业数据接口
    "industry_data": {
        "concept": {
            "name": "概念分类",
            "fields": "code,name,src",
            "description": "获取概念股分类"
        },
        "concept_detail": {
            "name": "概念股列表",
            "fields": "id,concept_name,ts_code,name,in_date,out_date",
            "description": "获取概念股列表数据"
        },
        "index_classify": {
            "name": "申万行业分类",
            "fields": "index_code,industry_name,level,industry_code,parent_code,src",
            "description": "获取申万行业分类"
        },
        "index_member": {
            "name": "申万行业成分",
            "fields": "index_code,con_code,con_name,in_date,out_date,is_new",
            "description": "申万行业成分"
        }
    },

    # 宏观经济数据接口
    "macro_data": {
        "shibor": {
            "name": "Shibor拆借利率",
            "fields": "date,on,1w,2w,1m,3m,6m,9m,1y",
            "description": "获取银行间同业拆借利率数据"
        },
        "libor": {
            "name": "Libor拆借利率",
            "fields": "date,curr_type,on,1w,1m,2m,3m,6m,12m",
            "description": "获取Libor拆借利率"
        },
        "hibor": {
            "name": "Hibor拆借利率",
            "fields": "date,on,1w,2w,1m,2m,3m,6m,12m",
            "description": "获取Hibor拆借利率"
        },
        "wz_index": {
            "name": "温州民间借贷利率",
            "fields": "date,index",
            "description": "获取温州民间借贷利率"
        }
    }
}

# 技术指标参数配置
TECHNICAL_PARAMS = {
    "moving_averages": {
        "short": [5, 10, 20],
        "medium": [50, 60],
        "long": [200, 250]
    },
    "volatility": {
        "window": 30,
        "annualization_factor": 252
    },
    "trend_scoring": {
        "price_change_threshold": 1.0,  # 1%
        "ma_slope_periods": 5,
        "score_range": [-2, 2]
    },
    "rsi": {
        "periods": [14, 21],
        "overbought": 70,
        "oversold": 30
    },
    "macd": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9
    },
    "bollinger_bands": {
        "period": 20,
        "std_dev": 2
    },
    "kdj": {
        "n": 9,
        "m1": 3,
        "m2": 3
    }
}

# 报告生成配置
REPORT_CONFIG = {
    "default_periods": {
        "short_term": 5,
        "medium_term": 30,
        "long_term": 200
    },
    "output_formats": {
        "markdown": ".md",
        "json": ".json", 
        "csv": ".csv"
    },
    "templates": {
        "background_scan": "背景扫描模板",
        "daily_report": "日报模板",
        "combined_report": "综合报告模板"
    }
}

def get_all_indices():
    """获取所有指数配置"""
    return {
        "A股": A_SHARE_INDICES,
        "美股": US_INDICES,
        "港股": HK_INDICES
    }

def get_indices_by_market(market: str):
    """按市场获取指数配置"""
    market_map = {
        "A股": A_SHARE_INDICES,
        "美股": US_INDICES, 
        "港股": HK_INDICES,
        "a_share": A_SHARE_INDICES,
        "us": US_INDICES,
        "hk": HK_INDICES
    }
    return market_map.get(market, {})

def get_symbol_by_name(name: str, market: str = None):
    """根据名称获取交易代码"""
    if market:
        indices = get_indices_by_market(market)
        return indices.get(name, {}).get("symbol")
    
    # 搜索所有市场
    all_indices = get_all_indices()
    for market_indices in all_indices.values():
        if name in market_indices:
            return market_indices[name]["symbol"]
    return None

def get_display_name(name: str, market: str = None):
    """根据名称获取显示名称"""
    if market:
        indices = get_indices_by_market(market)
        return indices.get(name, {}).get("display_name", name)

    # 搜索所有市场
    all_indices = get_all_indices()
    for market_indices in all_indices.values():
        if name in market_indices:
            return market_indices[name]["display_name"]
    return name

def get_tushare_api_info(category: str = None, api_name: str = None):
    """获取TuShare API信息"""
    if category and api_name:
        return TUSHARE_API_CONFIG.get(category, {}).get(api_name)
    elif category:
        return TUSHARE_API_CONFIG.get(category, {})
    else:
        return TUSHARE_API_CONFIG

def get_tushare_api_fields(category: str, api_name: str):
    """获取TuShare API字段信息"""
    api_info = get_tushare_api_info(category, api_name)
    if api_info:
        return api_info.get("fields", "").split(",")
    return []

def get_available_tushare_apis():
    """获取所有可用的TuShare API列表"""
    apis = {}
    for category, api_dict in TUSHARE_API_CONFIG.items():
        apis[category] = list(api_dict.keys())
    return apis

def get_technical_indicator_params(indicator: str = None):
    """获取技术指标参数配置"""
    if indicator:
        return TECHNICAL_PARAMS.get(indicator, {})
    return TECHNICAL_PARAMS

def search_tushare_api(keyword: str):
    """根据关键词搜索TuShare API"""
    results = []
    keyword_lower = keyword.lower()

    for category, api_dict in TUSHARE_API_CONFIG.items():
        for api_name, api_info in api_dict.items():
            name = api_info.get("name", "")
            description = api_info.get("description", "")

            if (keyword_lower in name.lower() or
                keyword_lower in description.lower() or
                keyword_lower in api_name.lower()):
                results.append({
                    "category": category,
                    "api_name": api_name,
                    "name": name,
                    "description": description,
                    "fields": api_info.get("fields", "")
                })

    return results


# 120背景扫描专用配置 - 确保AI_EXECUTION_WORKFLOW完整覆盖
BACKGROUND_SCAN_120D_CONFIG = {
    "required_assets": {
        "forex": {
            "priority_1": ["DXY", "USDCNY", "USDCNH"],  # 美元指数DXY外汇数据, USD/CNH离岸CFETS数据, USD/CNY在岸SAFE数据
            "priority_2": ["EURUSD", "GBPUSD", "USDJPY"]
        },
        "bond_yields": {
            "priority_1": ["US10Y", "CN10Y", "CN10Y_CDB"],  # US10Y国债收益率FRED数据, CN10Y国债收益率中债估值, CN10Y国开债收益率中债AAA代理
            "priority_2": ["DE10Y", "JP10Y"]
        },
        "indices": {
            "a_share": ["000001", "000300", "000905", "399001", "399006"],
            "us_stock": ["SPX", "IXIC", "DJI"],
            "hk_stock": ["HSI", "HSTECH"]
        },
        "commodities": {
            "priority_1": ["GC", "CL", "BZ", "HG", "BCOM", "GSG"],  # COMEX黄金、WTI原油、Brent原油、COMEX铜、BCOM指数、GSG ETF
            "energy": ["CL", "BZ"],                # WTI原油期货(NYMEX)、Brent原油期货(ICE)
            "base_metals": ["HG"],                 # COMEX铜期货
            "precious_metals": ["GC"],             # COMEX黄金期货
            "indices": ["BCOM", "GSG"],            # Bloomberg商品指数、S&P GSCI商品ETF
            "websearch_required": ["BCOM"]         # 需要WebSearch获取的商品
        }
    },
    "data_sources": {
        "forex": {
            "primary": "yahoo_finance",
            "fallback": ["websearch"]
        },
        "bond_yields": {
            "primary": "yahoo_finance",
            "proxy": "bond_etfs",
            "fallback": ["websearch"]
        },
        "calculation_methods": {
            "yield_from_etf": "基于债券ETF价格反推收益率变化",
            "duration_model": "久期模型：价格变化1%约对应收益率变化10bp（10年期债券）"
        }
    }
}

# 数据获取优先级配置
DATA_PRIORITY_CONFIG = {
    "汇率数据": {
        "DXY": ["yahoo_finance:DX-Y.NYB", "websearch"],
        "USDCNY": ["yahoo_finance:USDCNY=X", "websearch"],
        "USDCNH": ["yahoo_finance:USDCNH=X", "websearch"]
    },
    "收益率数据": {
        "US10Y": ["yahoo_finance:^TNX", "websearch"],
        "CN10Y": ["bond_etf_proxy:511010", "bond_etf_proxy:019649", "websearch"],
        "CN10Y_CDB": ["bond_etf_proxy:019950", "websearch"]
    },
    "商品期货数据": {
        "GC": ["yahoo_finance:GC=F", "websearch:COMEX黄金期货"],
        "CL": ["yahoo_finance:CL=F", "websearch:WTI原油价格"],
        "BZ": ["yahoo_finance:BZ=F", "websearch:Brent原油"],
        "HG": ["yahoo_finance:HG=F", "websearch:COMEX铜期货"],
        "BCOM": ["websearch:Bloomberg Commodity Index BCOM"],
        "GSG": ["yahoo_finance:GSG", "websearch:GSG ETF S&P GSCI"]
    }
}

# 导出所有配置
__all__ = [
    "A_SHARE_INDICES",
    "US_INDICES",
    "HK_INDICES",
    "BOND_ETFS",
    "BOND_YIELDS",
    "FOREX_PAIRS",
    "COMMODITY_FUTURES",
    "TECHNICAL_PARAMS",
    "TUSHARE_API_CONFIG",
    "REPORT_CONFIG",
    "BACKGROUND_SCAN_120D_CONFIG",
    "DATA_PRIORITY_CONFIG",
    "get_available_tushare_apis",
    "get_technical_indicator_params",
    "search_tushare_api"
]
