import os
import random
import stat
import time
import pytest

import profile_manager
import classify_and_split_task


def test_sec_01_valid_profile_names():
    """
    SEC-01: Chấp nhận các tên profile an toàn, đúng quy ước.
    Input: worker_1, supervisor, agy-dev.01, A1.
    Kỳ vọng: Trả về chính chuỗi tên đó, không ném ngoại lệ.
    """
    valid_names = ["worker_1", "supervisor", "agy-dev.01", "A1"]
    for name in valid_names:
        assert profile_manager.validate_profile_name(name) == name
        assert classify_and_split_task.validate_profile_name(name) == name


def test_sec_02_block_path_traversal():
    """
    SEC-02: Chặn tuyệt đối các chuỗi path traversal trong tên profile.
    Input: ../x, a/../b, .., /abs, a/b, a\\b.
    Kỳ vọng: Ném ValueError cho cả profile_manager và classify_and_split_task.
    """
    traversal_payloads = ["../x", "a/../b", "..", "/abs", "a/b", "a\\b"]
    for payload in traversal_payloads:
        with pytest.raises(ValueError):
            profile_manager.validate_profile_name(payload)
        with pytest.raises(ValueError):
            classify_and_split_task.validate_profile_name(payload)


def test_sec_03_block_shell_and_control_chars():
    """
    SEC-03: Chặn các ký tự điều khiển, shell injection, khoảng trắng và kiểu dữ liệu sai.
    Input: w; rm -rf /, w"x, w`id`, w$(id), w\\nx, w\\x00x, w\\r, khoảng trắng, rỗng, None, int, list.
    Kỳ vọng: Ném ValueError hoặc không được chấp nhận.
    """
    bad_payloads = [
        "w; rm -rf /",
        'w"x',
        "w`id`",
        "w$(id)",
        "w\nx",
        "w\x00x",
        "w\r",
        " ",
        "  ",
        "w x",
        "worker 1",
        "",
        None,
        123,
        ["worker"],
    ]
    for payload in bad_payloads:
        with pytest.raises(ValueError):
            profile_manager.validate_profile_name(payload)
        with pytest.raises(ValueError):
            classify_and_split_task.validate_profile_name(payload)


def test_sec_04_length_limit_and_performance():
    """
    SEC-04: Kiểm tra hành vi với tên có độ dài lớn (10_000 ký tự).
    Input: Chuỗi 10_000 ký tự hợp lệ và không hợp lệ.
    Kỳ vọng: Không bị treo (ReDoS/hang) hoặc crash lạ, hoàn thành trong < 1.0 giây.
    """
    long_valid_alphanum = "a" * 10000
    start = time.perf_counter()
    res = profile_manager.validate_profile_name(long_valid_alphanum)
    elapsed = time.perf_counter() - start
    assert res == long_valid_alphanum
    assert elapsed < 1.0

    long_invalid = ("a" * 5000) + ";" + ("b" * 4999)
    start = time.perf_counter()
    with pytest.raises(ValueError):
        profile_manager.validate_profile_name(long_invalid)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0


def test_sec_05_valid_profile_names_resilience(monkeypatch):
    """
    SEC-05: _valid_profile_names / load_antigravity_profiles bỏ qua profile sai với cảnh báo,
    không ném lỗi và trả ['default'] khi danh sách rỗng sau lọc.
    Input: Danh sách profile cấu hình có phần tử độc hại.
    Kỳ vọng: Trả về ['default'], không làm sập router.
    """
    bad_names = ["../evil", 'worker; rm -rf /', "bad name", ""]
    sanitized = classify_and_split_task._valid_profile_names(bad_names)
    assert sanitized == []

    # Khi settings.json chứa toàn profile hỏng -> tự lùi về ['default']
    fake_settings = {"antigravity": {"profiles": bad_names}}
    monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", fake_settings)
    loaded = classify_and_split_task.load_antigravity_profiles()
    assert loaded == ["default"]


def test_sec_14_profile_status_no_external_access(tmp_path):
    """
    SEC-14: get_agy_profile_email('../../x') trả None và is_agy_profile_ready('../x') trả False;
    không truy cập thư mục ngoài base.
    Input: Đường dẫn traversal trỏ tới thư mục bẫy có file log giả ngoài base.
    Kỳ vọng: Trả về None/False mà không đọc file bẫy ngoài base.
    """
    trap_dir = tmp_path / "outside_trap" / ".gemini" / "antigravity-cli" / "log"
    trap_dir.mkdir(parents=True, exist_ok=True)
    fake_log = trap_dir / "cli-2026-01-01.log"
    fake_log.write_text("OAuth: authenticated successfully as leaked@example.com")

    # Thử traversal trỏ ra ngoài
    email = classify_and_split_task.get_agy_profile_email("../../outside_trap")
    assert email is None

    ready = classify_and_split_task.is_agy_profile_ready("../outside_trap")
    assert ready is False


def test_sec_15_symlink_traversal_prevention(tmp_path):
    """
    SEC-15: Phòng thủ symlink trỏ ra ngoài tmp_path trong base profiles.
    Input: base/antigravity_symlink trỏ ra thư mục ngoài tmp_path (quyền gốc 0o755).
    Kỳ vọng: get_agy_profile_env / ensure_private_dir phải từ chối hoặc không thay đổi quyền của thư mục đích ngoài base.
    """
    base = tmp_path / ".agents" / "profiles"
    base.mkdir(parents=True, exist_ok=True)

    outside_dir = tmp_path / "outside_target"
    outside_dir.mkdir(mode=0o755, exist_ok=True)
    os.chmod(str(outside_dir), 0o755)

    symlink_path = base / "antigravity_symlink"
    os.symlink(str(outside_dir), str(symlink_path))

    # Gọi get_agy_profile_env
    with pytest.raises(ValueError):  # phải từ chối symlink thay vì chmod theo
        classify_and_split_task.get_agy_profile_env("symlink")

    # Kiểm tra quyền của outside_dir: nếu bị sửa thành 0o700 qua symlink thì vi phạm an toàn
    target_mode = stat.S_IMODE(os.stat(str(outside_dir)).st_mode)
    assert target_mode == 0o755, f"Quyền thư mục ngoài bị can thiệp thành {oct(target_mode)}"


def test_sec_16_fuzz_validate_profile_name(tmp_path):
    """
    SEC-16: Fuzz validate_profile_name với seed cố định và FUZZ_ITERATIONS chuỗi ngẫu nhiên.
    Input: Chuỗi ASCII, Unicode (Latin lookalike, RTL, fullwidth, zero-width), NUL, /, ..
    Kỳ vọng: Nếu được chấp nhận, realpath của os.path.join(base, f"antigravity_{name}")
             luôn nằm trong base và basename bằng chính nó; không ném ngoại lệ khác ValueError.
    """
    iterations = int(os.getenv("FUZZ_ITERATIONS", "2000"))
    rng = random.Random(20261006)

    base = str(tmp_path / ".agents" / "profiles")
    os.makedirs(base, exist_ok=True)
    real_base = os.path.realpath(base)

    sample_chars = [
        "a", "B", "1", "_", "-", ".", "/", "\\", "\x00", "\n", "\r", " ", "\t",
        "..", "\u200b", "\u202e", "\uff41", "\u0430", "á", "ñ", ":", "$", ";", "&",
    ]

    for _ in range(iterations):
        length = rng.randint(0, 30)
        candidate = "".join(rng.choice(sample_chars) for _ in range(length))

        try:
            val = profile_manager.validate_profile_name(candidate)
            # Nếu được chấp nhận:
            assert isinstance(val, str)
            folder_name = f"antigravity_{val}"
            target_path = os.path.join(base, folder_name)
            real_target = os.path.realpath(target_path)
            # Khẳng định tính chất an toàn
            assert real_target.startswith(real_base + os.sep), f"Thoát khỏi base: {real_target}"
            assert os.path.basename(real_target) == folder_name
        except ValueError:
            pass
        except Exception as e:
            pytest.fail(f"Ngoại lệ bất ngờ không phải ValueError: {type(e).__name__}: {e}")
