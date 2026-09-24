"""纸质备用谱页序核对核心的单元测试。运行：python -m pytest -q"""

from __future__ import annotations

import pytest

from app.print_audit import (
    INSERT,
    KEEP,
    REMOVE,
    REPLACE,
    PrintAuditError,
    audit_print_pages,
)


def _ops(result):
    return [(s.operation, s.position, s.observed_page, s.target_page) for s in result.steps]


def test_exact_order_is_all_keeps():
    r = audit_print_pages(4, [1, 2, 3, 4])
    assert r.operation_count == 0
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (KEEP, 1, 2, 2),
        (KEEP, 2, 3, 3),
        (KEEP, 3, 4, 4),
    ]


def test_empty_physical_stack_inserts_every_page_at_position_zero():
    r = audit_print_pages(3, [])
    assert r.operation_count == 3
    assert _ops(r) == [
        (INSERT, 0, None, 1),
        (INSERT, 0, None, 2),
        (INSERT, 0, None, 3),
    ]


def test_single_missing_page_inserted_before_original_position():
    # 缺第 2 页：补入位置 1（插在原输入位置 1 之前，末尾允许数组长度）
    r = audit_print_pages(5, [1, 3, 4, 5])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (INSERT, 1, None, 2),
        (KEEP, 1, 3, 3),
        (KEEP, 2, 4, 4),
        (KEEP, 3, 5, 5),
    ]


def test_insert_at_end_uses_array_length_position():
    r = audit_print_pages(4, [1, 2, 3])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (KEEP, 1, 2, 2),
        (KEEP, 2, 3, 3),
        (INSERT, 3, None, 4),
    ]


def test_duplicate_page_removed_as_extra():
    # 第 2 页重复夹带：同成本下替换优先于“移除+补入”，
    # 故把第二张 2 替换为 3（错页），后续保留
    r = audit_print_pages(5, [1, 2, 2, 4, 5])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (KEEP, 1, 2, 2),
        (REPLACE, 2, 2, 3),
        (KEEP, 3, 4, 4),
        (KEEP, 4, 5, 5),
    ]


def test_extra_page_beyond_last_is_removed():
    # 正确页 1..3，实物多出一张且在末尾：移除原位置 3 的 4
    r = audit_print_pages(3, [1, 2, 3, 4])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (KEEP, 1, 2, 2),
        (KEEP, 2, 3, 3),
        (REMOVE, 3, 4, None),
    ]


def test_extra_page_in_middle_is_removed():
    r = audit_print_pages(3, [1, 9, 2, 3])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (REMOVE, 1, 9, None),
        (KEEP, 2, 2, 2),
        (KEEP, 3, 3, 3),
    ]


def test_wrong_page_replaced():
    r = audit_print_pages(5, [1, 9, 3, 4, 5])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (REPLACE, 1, 9, 2),
        (KEEP, 2, 3, 3),
        (KEEP, 3, 4, 4),
        (KEEP, 4, 5, 5),
    ]


def test_mixed_keep_replace_remove_insert():
    # 目标 1..5，实物 [9, 2, 2, 4]：
    # 替换 9->1、保留 2、替换 2->3、保留 4、末尾补 5（同成本替换优先于移除+补入）
    r = audit_print_pages(5, [9, 2, 2, 4])
    assert r.operation_count == 3
    assert _ops(r) == [
        (REPLACE, 0, 9, 1),
        (KEEP, 1, 2, 2),
        (REPLACE, 2, 2, 3),
        (KEEP, 3, 4, 4),
        (INSERT, 4, None, 5),
    ]


def test_replaced_target_keeps_chain_alignment():
    # 目标 1..3，实物 [3, 3]：替换第一张 3->1、补入 2（位置 1，插在原 3 之前）、保留第二张 3
    r = audit_print_pages(3, [3, 3])
    assert r.operation_count == 2
    assert _ops(r) == [
        (REPLACE, 0, 3, 1),
        (INSERT, 1, None, 2),
        (KEEP, 1, 3, 3),
    ]


def test_reversed_two_pages_use_two_replaces_not_remove_plus_insert():
    # [2,1] -> [1,2]：两次替换 = 2；移除+补入也是 2，替换优先
    r = audit_print_pages(2, [2, 1])
    assert r.operation_count == 2
    assert _ops(r) == [
        (REPLACE, 0, 2, 1),
        (REPLACE, 1, 1, 2),
    ]


def test_duplicate_with_missing_is_one_replace():
    # [1,1,3] 对 [1,2,3]：替换优先（1 步），不移除+补入（2 步）
    r = audit_print_pages(3, [1, 1, 3])
    assert r.operation_count == 1
    assert _ops(r) == [
        (KEEP, 0, 1, 1),
        (REPLACE, 1, 1, 2),
        (KEEP, 2, 3, 3),
    ]


def test_out_of_range_pages_are_treated_as_wrong_pages():
    # 全部越界页码：每页替换，成本 = 页数
    r = audit_print_pages(2, [7, 8])
    assert r.operation_count == 2
    assert all(s.operation == REPLACE for s in r.steps)


def test_operation_count_equals_edit_distance_against_brute_force():
    """随机小例：结果成本与“保留/替换/移除/补入”编辑距离的暴力递推一致。"""
    import random

    rng = random.Random(20260924)
    for _ in range(300):
        n = rng.randint(1, 6)
        m = rng.randint(0, 7)
        # 页码取 1..n+2，制造重复与越界错页
        scanned = [rng.randint(1, n + 2) for _ in range(m)]
        r = audit_print_pages(n, scanned)

        def dist(i: int, j: int) -> int:
            if i == m:
                return n - j
            if j == n:
                return m - i
            diag = dist(i + 1, j + 1) + (0 if scanned[i] == j + 1 else 1)
            return min(diag, 1 + dist(i + 1, j), 1 + dist(i, j + 1))

        assert r.operation_count == dist(0, 0), (n, scanned)


def test_steps_reproduce_target_when_applied_in_order():
    """按步骤语义模拟编辑：替换/保留占实物位、移除跳过实物、补入插入目标页，
    最终序列恰为 1..page_count。"""
    import random

    rng = random.Random(4242)
    for _ in range(200):
        n = rng.randint(1, 8)
        scanned = [rng.randint(1, n + 2) for _ in range(rng.randint(0, 9))]
        r = audit_print_pages(n, scanned)

        result: list[int] = []
        i = 0
        for step in r.steps:
            if step.operation in (KEEP, REPLACE):
                assert step.position == i
                result.append(step.target_page)
                i += 1
            elif step.operation == REMOVE:
                assert step.position == i
                i += 1
            else:  # INSERT
                assert step.position == i
                result.append(step.target_page)
        assert i == len(scanned)
        assert result == list(range(1, n + 1))


def test_result_is_deterministic():
    a = audit_print_pages(6, [2, 2, 5, 5, 7])
    b = audit_print_pages(6, [2, 2, 5, 5, 7])
    assert _ops(a) == _ops(b)


def test_reject_non_positive_page_count():
    with pytest.raises(PrintAuditError, match="规划页数必须为正整数"):
        audit_print_pages(0, [1])
    with pytest.raises(PrintAuditError, match="规划页数必须为正整数"):
        audit_print_pages(-3, [])


def test_reject_bool_page_count():
    with pytest.raises(PrintAuditError, match="规划页数必须为正整数"):
        audit_print_pages(True, [])  # type: ignore[arg-type]


def test_page_count_over_limit():
    with pytest.raises(PrintAuditError, match="超过上限 500"):
        audit_print_pages(501, [])


def test_scanned_pages_must_be_list():
    with pytest.raises(PrintAuditError, match="scanned_pages 必须是数组"):
        audit_print_pages(3, (1, 2))  # type: ignore[arg-type]


def test_reject_float_string_none_and_bool_pages():
    for bad in (1.0, 2.5, "3", None, True, False):
        with pytest.raises(PrintAuditError, match="必须为正整数"):
            audit_print_pages(3, [1, bad, 3])  # type: ignore[list-item]


def test_reject_zero_and_negative_pages():
    with pytest.raises(PrintAuditError, match="必须为正整数"):
        audit_print_pages(3, [0, 2])
    with pytest.raises(PrintAuditError, match="必须为正整数"):
        audit_print_pages(3, [-1])


def test_scanned_pages_over_limit():
    with pytest.raises(PrintAuditError, match="实物页数（501）超过上限 500"):
        audit_print_pages(3, [1] * 501)


def test_boundary_lengths_500_are_allowed_and_fast():
    # 规模上限：500 目标页、500 实物页，DP 为 501×501，应即时完成
    r = audit_print_pages(500, list(range(1, 501)))
    assert r.operation_count == 0
    assert len(r.steps) == 500

    r = audit_print_pages(500, [500] * 500)
    # 仅一个 500 可保留，其余 499 张依次替换为 1..499（替换优先于移除+补入）
    assert r.operation_count == 499
    assert len(r.steps) == 500
