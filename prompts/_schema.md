# 字段定义与 Schema（供提示词与校验器共享）

> 本文件是**唯一的字段定义来源**。`prompts/extract_bid_notice.md` 引用它，
> `agent/orchestrator.py` 用它做输出 Schema 校验。
> 修改字段时只改这里，避免提示词与代码不一致。

## 字段表

| 字段名 | 中文名 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `company` | 中标公司 | string | ✅ | 逐字引用原文 |
| `project` | 项目名称 | string | ✅ | 逐字引用；同时作为事件主键的一部分 |
| `bidder` | 招标方 | string | ✅ | **非中标方**；历史字段名，界面与提示词均明确为招标方 |
| `award_amount_raw` | 中标金额原文 | string \| null | ⭕ 可为 null | 保留币种/逗号/单位；**未披露时为 null，不填零** |
| `currency` | 币种 | string \| null | ⭕ 可为 null | 与 `award_amount_raw` 同生共死 |
| `award_date` | 中标日期 | string \| null | ⭕ 可为 null | 逐字引用，不改写格式 |
| `disclosure_date` | 披露日期 | string \| null | ⭕ 可为 null | 每页披露日期适用于本页项目 |

## 数据模型约束

```
FIELDS = ("company", "project", "bidder", "award_amount_raw",
          "currency", "award_date", "disclosure_date")
```

## 缺失的表示

统一使用 **`null`**（Python `None`）。**禁止**用下列值表示缺失：

| 禁止值 | 原因 |
|---|---|
| `0` / `0.0` | 会被误读为"金额为零" |
| `""` 以外的占位符（如 `N/A`、`-`、`未披露`） | 归一化阶段另有 `_MISSING` 集合处理，字段层保持干净 |
| 预算/合计金额 | 口径不同，属**预算串用**错误 |

> `""`（空字符串）在模型输出中允许，由归一化阶段转成 `null`。

## 金额口径规则（防止预算串用）

以下词汇出现在金额附近时，**不得**作为单项目中标金额：

```
预算 / 合计 / 汇总 / 总计 / 累计 / 总投资 / 最高限价 / 项目总额
```

校验位置（两处独立拦截）：
1. `prototype/validation.py`：`normalize_amount()` 的正则拦截
2. `tools/calculate_tool.py`：金额需紧邻「中标金额 / 中标价」标签才进入计算
