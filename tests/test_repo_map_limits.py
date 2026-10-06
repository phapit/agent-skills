import os
import pytest

import repo_map


def test_sec_30_repo_map_source_bytes_limits(tmp_path):
    """
    SEC-30: Kiểm tra giới hạn kích thước file nguồn trong repo_map:
    - File lớn hơn MAX_SOURCE_BYTES bị bỏ qua (tránh OOM).
    - File đúng bằng MAX_SOURCE_BYTES được đọc.
    - File nhỏ bình thường được đọc.
    - File không đọc được (quyền 000) không làm crash tiến trình.
    """
    max_bytes = repo_map.MAX_SOURCE_BYTES

    # 1. File nhỏ bình thường
    small_file = tmp_path / "small.py"
    small_file.write_text("def small_func():\n    pass\n")

    # 2. File lớn hơn ngưỡng (max_bytes + 100 bytes)
    oversized_file = tmp_path / "oversized.py"
    # Header chứa hàm định nghĩa, phần sau nhồi comment cho vượt ngưỡng
    oversized_content = "def oversized_func():\n    pass\n" + ("# " + "A" * 60 + "\n") * ((max_bytes // 60) + 10)
    oversized_file.write_text(oversized_content)
    assert oversized_file.stat().st_size > max_bytes

    # 3. File đúng bằng ngưỡng (exact max_bytes)
    exact_file = tmp_path / "exact.py"
    exact_header = "def exact_func():\n    pass\n"
    padding = "#" * (max_bytes - len(exact_header))
    exact_file.write_text(exact_header + padding)
    assert exact_file.stat().st_size == max_bytes

    # 4. File quyền 0o000 (không đọc được)
    unreadable_file = tmp_path / "unreadable.py"
    unreadable_file.write_text("def unreadable_func():\n    pass\n")
    try:
        os.chmod(str(unreadable_file), 0o000)
    except OSError:
        pass

    files = [str(small_file), str(oversized_file), str(exact_file), str(unreadable_file)]
    defs, refs, sigs = repo_map.extract_symbols(files)

    # Khôi phục quyền để pytest dọn dẹp tmp_path
    try:
        os.chmod(str(unreadable_file), 0o644)
    except OSError:
        pass

    # Khẳng định
    # - small_func được trích xuất
    assert "small_func" in defs
    # - exact_func được trích xuất
    assert "exact_func" in defs
    # - oversized_func bị bỏ qua hoàn toàn
    assert "oversized_func" not in defs
    # - unreadable_func không làm crash và không có trong defs
    assert "unreadable_func" not in defs
