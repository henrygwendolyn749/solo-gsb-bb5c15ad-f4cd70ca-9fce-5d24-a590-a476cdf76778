"""纸质备用谱页序核对核心。

纸质备用谱（手抄/打印的页序）可能与电子规划方案不一致：漏抄了缺页、重复
夹带了多页、某张纸写错了页码。本模块以已保存规划的正确页序
``1, 2, ..., page_count`` 为目标序列，把按实物顺序抄录的页码
``scanned_pages``（允许为空、允许重复、允许出现越界错页）与目标序列做对齐，
求把实物页序修正为正确页序的**最少操作数**与一条**确定的修正步骤序列**。

操作模型（序列编辑距离，三种修正操作各计一次）：

- **保留 keep**：该位置实物页码本就正确，零成本；
- **替换 replace（错页）**：把该位置观察到的错页当作目标页，一次操作；
- **移除 remove（多页）**：抽走该位置多余的实物页（含重复夹带），一次操作；
- **补入 insert（缺页）**：在指定位置之前插入缺失的目标页，一次操作。

最少操作数即两序列间的 Levenshtein 编辑距离（保留等价于零成本的替换对角
转移）。同成本方案可能不止一条（例如同一步既可以替换也可以移除+补入），
约定在每一步上按 **保留 → 替换 → 移除 → 补入** 的顺序选取仍处于某条最优
路径上的第一种操作，从而对任意输入都给出唯一、可复现的步骤序列。

求解用后缀 DP：``cost[i][j]`` 表示把 ``scanned_pages[i:]`` 修正为
``1+j..page_count`` 的最少操作数，自右下角向左上填充；随后自左上角贪心
重构：在状态 (i, j) 上依次试探保留、替换、移除、补入四条转移，选择第一条
使总成本等于 ``cost[0][0]`` 的操作。规模上限均为 500，DP 表 O(n·m)。

每个步骤的 ``position`` 一律指**原输入数组**中的 0 基位置：保留/替换/移除
作用于该位置的原实物页；补入表示插在该位置之前，取值可为数组长度（末尾）。

本模块仅依赖标准库，便于脱离 Web 层直接单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# 规划页数与实物页数各自的上限
MAX_PAGE_COUNT = 500
MAX_SCANNED_PAGES = 500

# 四种操作的稳定标识（接口原样输出）
KEEP = "keep"
REPLACE = "replace"
REMOVE = "remove"
INSERT = "insert"


class PrintAuditError(ValueError):
    """纸质谱页序核对输入不合法：页码非正整数、数组超限等。"""


@dataclass(frozen=True)
class AuditStep:
    """一步修正（或保留）操作。

    :param operation: ``keep`` 保留 / ``replace`` 替换错页 /
        ``remove`` 移除多页 / ``insert`` 补入缺页
    :param position: 原输入 ``scanned_pages`` 中的 0 基位置；
        补入操作表示插在该位置之前，等于数组长度时表示末尾
    :param observed_page: 该位置观察到的实物页码；补入时为 None
    :param target_page: 应对齐的目标页码（1..page_count）；移除时为 None
    """

    operation: str
    position: int
    observed_page: Optional[int]
    target_page: Optional[int]


@dataclass(frozen=True)
class PrintAudit:
    """核对结果：最少操作数与一条确定的完整对齐步骤序列（含保留步）。"""

    page_count: int
    scanned_pages: List[int]
    # 最少修正操作数（仅统计替换/移除/补入，不含保留）
    operation_count: int
    steps: List[AuditStep]


def audit_print_pages(page_count: int, scanned_pages: object) -> PrintAudit:
    """核对实物页序与规划页序 1..page_count 的差异并给出修正步骤。

    :param page_count: 已保存规划的总页数（正确页序为 1..page_count）
    :param scanned_pages: 按实物顺序抄录的页码列表；可为空，元素允许重复、
        允许大于 page_count（视为错页）
    :raises PrintAuditError: 规划页数非法或超 500、实物页数超 500、
        实物页码不是严格正整数（拒绝浮点与布尔）
    """
    if not isinstance(page_count, int) or isinstance(page_count, bool):
        raise PrintAuditError(f"规划页数必须为正整数（收到 {page_count!r}）")
    if page_count < 1:
        raise PrintAuditError(f"规划页数必须为正整数（收到 {page_count}）")
    if page_count > MAX_PAGE_COUNT:
        raise PrintAuditError(
            f"规划页数（{page_count}）超过上限 {MAX_PAGE_COUNT}，无法核对"
        )

    if not isinstance(scanned_pages, list):
        raise PrintAuditError("scanned_pages 必须是数组（按实物顺序抄录的页码）")
    if len(scanned_pages) > MAX_SCANNED_PAGES:
        raise PrintAuditError(
            f"实物页数（{len(scanned_pages)}）超过上限 {MAX_SCANNED_PAGES}"
        )
    for idx, page in enumerate(scanned_pages):
        if not isinstance(page, int) or isinstance(page, bool):
            raise PrintAuditError(
                f"第 {idx + 1} 个实物页码必须为正整数（收到 {page!r}），"
                "不接受小数、字符串或布尔值"
            )
        if page < 1:
            raise PrintAuditError(
                f"第 {idx + 1} 个实物页码必须为正整数（收到 {page}）"
            )

    m = len(scanned_pages)
    n = page_count
    target = list(range(1, n + 1))

    # 后缀 DP：cost[i][j] = 把 scanned[i:] 修正为 target[j:] 的最少操作数
    cost = [[0] * (n + 1) for _ in range(m + 1)]
    for j in range(n + 1):
        cost[m][j] = n - j  # 实物已耗尽：剩余目标页全部补入
    for i in range(m + 1):
        cost[i][n] = m - i  # 目标已耗尽：剩余实物页全部移除
    for i in range(m - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            # 替换（错页）：对角转移，计一次
            best = 1 + cost[i + 1][j + 1]
            # 保留：页码一致时的零成本对角转移
            if scanned_pages[i] == target[j]:
                best = min(best, cost[i + 1][j + 1])
            # 移除（多页）：消费一个实物页
            best = min(best, 1 + cost[i + 1][j])
            # 补入（缺页）：消费一个目标页
            best = min(best, 1 + cost[i][j + 1])
            cost[i][j] = best

    # 自左上角贪心重构：同成本时按 保留 → 替换 → 移除 → 补入 选取
    steps: List[AuditStep] = []
    i = j = 0
    while i < m or j < n:
        if i < m and j < n:
            if (
                scanned_pages[i] == target[j]
                and cost[i + 1][j + 1] == cost[i][j]
            ):
                steps.append(AuditStep(KEEP, i, scanned_pages[i], target[j]))
                i += 1
                j += 1
                continue
            if 1 + cost[i + 1][j + 1] == cost[i][j]:
                steps.append(AuditStep(REPLACE, i, scanned_pages[i], target[j]))
                i += 1
                j += 1
                continue
        if i < m and 1 + cost[i + 1][j] == cost[i][j]:
            steps.append(AuditStep(REMOVE, i, scanned_pages[i], None))
            i += 1
            continue
        # 其余情况必为补入（j < n 由循环条件保证）
        steps.append(AuditStep(INSERT, i, None, target[j]))
        j += 1

    operation_count = sum(1 for step in steps if step.operation != KEEP)
    assert operation_count == cost[0][0]

    return PrintAudit(
        page_count=page_count,
        scanned_pages=list(scanned_pages),
        operation_count=operation_count,
        steps=steps,
    )
