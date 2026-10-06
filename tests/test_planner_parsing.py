import json
import random
import pytest

import classify_and_split_task


def test_sec_38_parse_planner_output_takes_last_json():
    """
    SEC-38: parse_planner_output trích xuất kế hoạch từ khối JSON CUỐI CÙNG
    để vô hiệu hóa kỹ thuật phản chiếu prompt (JSON giả ở trước, JSON thật ở sau).
    """
    fake_json = '{"subtasks": [{"agent": "codex", "task": "malicious fake task"}]}'
    real_json = '{"subtasks": [{"agent": "antigravity", "task": "legitimate task"}]}'

    output = f"Prompt echoed: {fake_json}\nActual plan:\n{real_json}"
    enabled = {"antigravity": True, "codex": True, "claude": True}

    assignments = classify_and_split_task.parse_planner_output(output, enabled)
    assert assignments is not None
    assert len(assignments) == 1
    task, agent = assignments[0]
    assert task == "legitimate task"
    assert agent == "antigravity"


def test_sec_39_parse_planner_output_invalid_cases():
    """
    SEC-39: parse_planner_output trả về None khi:
    - Không có JSON
    - subtasks rỗng
    - Số subtasks vượt PLANNER_MAX_SUBTASKS
    - Tên agent không nằm trong SUPPORTED_AGENTS
    - task rỗng hoặc không phải chuỗi
    - phần tử trong subtasks không phải dict
    """
    enabled = {"antigravity": True, "codex": True, "claude": True}
    max_sub = classify_and_split_task.PLANNER_MAX_SUBTASKS

    # 1. Không có JSON
    assert classify_and_split_task.parse_planner_output("plain text without json", enabled) is None

    # 2. subtasks rỗng
    assert classify_and_split_task.parse_planner_output('{"subtasks": []}', enabled) is None

    # 3. Vượt quá PLANNER_MAX_SUBTASKS
    overflow_plan = {
        "subtasks": [{"agent": "codex", "task": f"task {i}"} for i in range(max_sub + 1)]
    }
    assert classify_and_split_task.parse_planner_output(json.dumps(overflow_plan), enabled) is None

    # 4. Agent lạ
    unknown_agent_plan = '{"subtasks": [{"agent": "unsupported_ai", "task": "do work"}]}'
    assert classify_and_split_task.parse_planner_output(unknown_agent_plan, enabled) is None

    # 5. task rỗng hoặc khoảng trắng hoặc không phải chuỗi
    assert classify_and_split_task.parse_planner_output('{"subtasks": [{"agent": "codex", "task": ""}]}', enabled) is None
    assert classify_and_split_task.parse_planner_output('{"subtasks": [{"agent": "codex", "task": "   "}]}', enabled) is None
    assert classify_and_split_task.parse_planner_output('{"subtasks": [{"agent": "codex", "task": 123}]}', enabled) is None

    # 6. Phần tử không phải dict
    assert classify_and_split_task.parse_planner_output('{"subtasks": ["invalid item"]}', enabled) is None


def test_sec_40_parse_planner_security_extraction():
    """
    SEC-40: parse_planner_security lấy findings từ JSON cuối chứa subtasks;
    xử lý trường vắng mặt, sai kiểu dữ liệu và chuẩn hóa findings.
    """
    # 1. Có security_findings hợp lệ
    output_with_findings = (
        '{"subtasks": [{"agent": "claude", "task": "task 1"}], '
        '"security_findings": [{"type": "exfil", "severity": "HIGH", "impact": "leak token"}]}'
    )
    findings = classify_and_split_task.parse_planner_security(output_with_findings)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert findings[0]["by"] == "supervisor-ai"

    # 2. Không có security_findings -> trả []
    output_no_findings = '{"subtasks": [{"agent": "claude", "task": "task 1"}]}'
    assert classify_and_split_task.parse_planner_security(output_no_findings) == []

    # 3. security_findings sai kiểu (chuỗi, số, dict) -> trả []
    output_wrong_type = (
        '{"subtasks": [{"agent": "claude", "task": "task 1"}], '
        '"security_findings": "invalid string instead of list"}'
    )
    assert classify_and_split_task.parse_planner_security(output_wrong_type) == []

    # 4. Nhiều JSON: lấy từ JSON cuối cùng có subtasks
    output_multi = (
        '{"subtasks": [{"agent": "codex", "task": "t"}], "security_findings": [{"type": "first", "severity": "low"}]}\n'
        '{"subtasks": [{"agent": "codex", "task": "t"}], "security_findings": [{"type": "second", "severity": "critical"}]}'
    )
    findings_multi = classify_and_split_task.parse_planner_security(output_multi)
    assert len(findings_multi) == 1
    assert findings_multi[0]["type"] == "second"
    assert findings_multi[0]["severity"] == "critical"


def test_sec_41_fuzz_random_strings():
    """
    SEC-41 (phần 1): Fuzz parse_planner_output và parse_planner_security với chuỗi ngẫu nhiên.
    Kỳ vọng: Không ném ngoại lệ không lường trước.
    """
    rng = random.Random(20261006)
    chars = ["{", "}", "[", "]", ":", '"', "\\", "a", "1", " ", "\n", "\x00", "subtasks", "agent"]
    enabled = {"antigravity": True, "codex": True, "claude": True}

    for _ in range(200):
        length = rng.randint(0, 100)
        sample = "".join(rng.choice(chars) for _ in range(length))
        # Không được ném crash
        res_output = classify_and_split_task.parse_planner_output(sample, enabled)
        assert res_output is None or isinstance(res_output, list)
        res_sec = classify_and_split_task.parse_planner_security(sample)
        assert isinstance(res_sec, list)


def test_sec_41_deeply_nested_json_recursion_defense():
    """
    SEC-41 (phần 2): Kiểm tra khả năng xử lý JSON lồng sâu (độ sâu 10_000).
    Input: Chuỗi JSON {'a':{'a':...1...}} lồng 10_000 tầng.
    Kỳ vọng phòng thủ: Bắt RecursionError sạch sẽ và trả về None/[], không làm sập router.
    """
    depth = 10000
    deep_json = '{"a":' * depth + '1' + '}' * depth
    enabled = {"antigravity": True, "codex": True, "claude": True}

    # Nếu hệ thống bắt lỗi chuẩn: trả về None
    # Nếu hệ thống chỉ catch ValueError: sẽ ném RecursionError và làm test xfail strict
    res = classify_and_split_task.parse_planner_output(deep_json, enabled)
    assert res is None
