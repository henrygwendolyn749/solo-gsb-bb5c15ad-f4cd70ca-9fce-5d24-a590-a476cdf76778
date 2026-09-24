"""纸质备用谱页序核对接口的端到端测试（FastAPI TestClient + 临时 SQLite）。"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """以临时 DATA_DIR 重新加载 app.main，得到隔离的服务实例。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        yield c


def _create_plan(client, page_count: int) -> str:
    # 每小节高度 1、页高 2（页间静默足够）-> 每两小节一页
    n = page_count * 2
    resp = client.post(
        "/api/v1/plans",
        json={
            "measure_heights": [1] * n,
            "silence_seconds": [5] * (n - 1) + [0],
            "page_height": 2,
            "min_turn_time": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["page_count"] == page_count
    return resp.json()["id"]


def test_print_audit_exact_match(client):
    plan_id = _create_plan(client, 4)
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": [1, 2, 3, 4]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == plan_id
    assert body["page_count"] == 4
    assert body["operation_count"] == 0
    assert body["request"] == {"scanned_pages": [1, 2, 3, 4]}
    assert [s["operation"] for s in body["steps"]] == ["keep"] * 4
    assert body["steps"][0] == {
        "operation": "keep",
        "position": 0,
        "observed_page": 1,
        "target_page": 1,
    }


def test_print_audit_missing_duplicate_wrong_together(client):
    plan_id = _create_plan(client, 5)
    # 实物 [1,2,2,4,5]：第 2 张 2 视为错页替换为 3（同成本替换优先于移除+补入）
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": [1, 2, 2, 4, 5]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["operation_count"] == 1
    assert body["steps"] == [
        {"operation": "keep", "position": 0, "observed_page": 1, "target_page": 1},
        {"operation": "keep", "position": 1, "observed_page": 2, "target_page": 2},
        {"operation": "replace", "position": 2, "observed_page": 2, "target_page": 3},
        {"operation": "keep", "position": 3, "observed_page": 4, "target_page": 4},
        {"operation": "keep", "position": 4, "observed_page": 5, "target_page": 5},
    ]


def test_print_audit_insert_step_shape(client):
    plan_id = _create_plan(client, 4)
    # 缺第 3 页：补在原位置 2 之前（即第 3 张实物页 4 之前）
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": [1, 2, 4]},
    )
    assert resp.status_code == 200, resp.text
    steps = resp.json()["steps"]
    assert steps == [
        {"operation": "keep", "position": 0, "observed_page": 1, "target_page": 1},
        {"operation": "keep", "position": 1, "observed_page": 2, "target_page": 2},
        {"operation": "insert", "position": 2, "observed_page": None, "target_page": 3},
        {"operation": "keep", "position": 2, "observed_page": 4, "target_page": 4},
    ]


def test_print_audit_remove_step_shape(client):
    plan_id = _create_plan(client, 3)
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": [1, 7, 2, 3]},
    )
    assert resp.status_code == 200, resp.text
    steps = resp.json()["steps"]
    assert steps[1] == {
        "operation": "remove",
        "position": 1,
        "observed_page": 7,
        "target_page": None,
    }
    assert resp.json()["operation_count"] == 1


def test_print_audit_empty_scanned_pages(client):
    plan_id = _create_plan(client, 3)
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": []},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["operation_count"] == 3
    assert body["steps"] == [
        {"operation": "insert", "position": 0, "observed_page": None, "target_page": 1},
        {"operation": "insert", "position": 0, "observed_page": None, "target_page": 2},
        {"operation": "insert", "position": 0, "observed_page": None, "target_page": 3},
    ]


def test_print_audit_out_of_range_page_allowed(client):
    plan_id = _create_plan(client, 2)
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": [9, 9]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["operation_count"] == 2
    assert [s["operation"] for s in body["steps"]] == ["replace", "replace"]


def test_print_audit_plan_not_found(client):
    resp = client.post(
        "/api/v1/plans/no-such-plan/print-audit",
        json={"scanned_pages": [1]},
    )
    assert resp.status_code == 404
    assert "规划结果不存在" in resp.json()["detail"]


def test_print_audit_rejects_bad_inputs(client):
    plan_id = _create_plan(client, 3)
    url = f"/api/v1/plans/{plan_id}/print-audit"

    for bad_payload in (
        {"scanned_pages": [1, True, 3]},       # 布尔值
        {"scanned_pages": [1, 2.0, 3]},        # 浮点（会被强转，须拒绝）
        {"scanned_pages": [1, 2.5, 3]},
        {"scanned_pages": [0, 2]},             # 零
        {"scanned_pages": [1, -2]},            # 负数
        {"scanned_pages": ["1", "2"]},         # 字符串
        {"scanned_pages": [1, None]},          # null
        {"scanned_pages": "1,2,3"},            # 非数组
        {},                                    # 缺字段
        {"scanned_pages": [1] * 501},          # 超 500
        {"scanned_pages": [1, 2], "extra": 1}, # 多余字段
    ):
        resp = client.post(url, json=bad_payload)
        assert resp.status_code == 422, bad_payload


def test_print_audit_plan_over_500_pages_returns_422(client):
    # 构造 501 页规划（501×2 = 1002 小节，每两小节一页）
    plan_id = _create_plan(client, 501)
    resp = client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": []},
    )
    assert resp.status_code == 422
    assert "超过上限 500" in resp.json()["detail"]


def test_print_audit_does_not_mutate_saved_plan(client):
    plan_id = _create_plan(client, 3)
    before = client.get(f"/api/v1/plans/{plan_id}").json()
    client.post(
        f"/api/v1/plans/{plan_id}/print-audit",
        json={"scanned_pages": [2, 2]},
    )
    after = client.get(f"/api/v1/plans/{plan_id}").json()
    assert before == after
