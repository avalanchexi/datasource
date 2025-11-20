#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuShare兼容性补丁 - 修复pandas 2.0+兼容性问题
"""
import pandas as pd
from loguru import logger


def monkey_patch_tushare():
    """
    为TuShare添加pandas 2.0+兼容性补丁
    """
    try:
        # 如果pandas版本>=2.0且DataFrame没有append方法，则添加补丁
        if not hasattr(pd.DataFrame, 'append'):
            def append_replacement(self, other, ignore_index=False, **kwargs):
                """
                pandas 2.0+兼容的append方法替代
                """
                if ignore_index:
                    return pd.concat([self, other], ignore_index=True)
                else:
                    return pd.concat([self, other])

            # 动态添加append方法到DataFrame类
            pd.DataFrame.append = append_replacement
            logger.info("Applied TuShare compatibility patch: added DataFrame.append method")

        # 修复read_json警告 (在实际调用时处理)
        logger.info("TuShare compatibility patches applied successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to apply TuShare compatibility patch: {e}")
        return False


def safe_get_today_all():
    """
    安全版本的get_today_all，处理兼容性问题
    """
    try:
        import tushare as ts

        # 应用补丁
        monkey_patch_tushare()

        # 尝试调用原始方法
        return ts.get_today_all()

    except Exception as e:
        logger.error(f"get_today_all failed even with patch: {e}")
        # 返回空DataFrame作为兜底
        return pd.DataFrame(columns=['code', 'name', 'changepercent', 'trade', 'open', 'high', 'low', 'settlement', 'volume', 'turnoverratio'])


if __name__ == "__main__":
    # 测试补丁
    monkey_patch_tushare()
    print(f"DataFrame has append method: {hasattr(pd.DataFrame, 'append')}")

    # 测试TuShare调用
    result = safe_get_today_all()
    print(f"Test result type: {type(result)}")
    if hasattr(result, 'shape'):
        print(f"Shape: {result.shape}")