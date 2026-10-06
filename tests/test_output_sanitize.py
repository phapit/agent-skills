import random
import time
import pytest

from classify_and_split_task import sanitize_terminal_text


def test_sec_27_sanitize_terminal_text_strips_ansi_and_ctrl():
    """
    SEC-27: Xóa màu, xóa màn hình, OSC title, \\r, \\x00, \\x7f; giữ \\n và \\t.
    """
    # 1. Màu ANSI
    assert sanitize_terminal_text("\x1b[31mRed Text\x1b[0m") == "Red Text"

    # 2. Xóa màn hình \x1b[2J
    assert sanitize_terminal_text("\x1b[2JCleaned") == "Cleaned"

    # 3. OSC đặt tiêu đề với \x07 (BEL) và \x1b\\ (ST)
    assert sanitize_terminal_text("\x1b]0;Title\x07Body") == "Body"
    assert sanitize_terminal_text("\x1b]0;Title2\x1b\\Next") == "Next"

    # 4. Ký tự điều khiển: \r, \x00, \x7f bị xóa; \n, \t được giữ
    raw = "Line1\r\n\tIndented\x00Null\x7fDEL"
    expected = "Line1\n\tIndentedNullDEL"
    assert sanitize_terminal_text(raw) == expected


def test_sec_28_partial_and_cut_off_escape():
    """
    SEC-28: Escape sequence bị cắt dở (\\x1b[, \\x1b) không để lại ký tự \\x1b.
    """
    assert "\x1b" not in sanitize_terminal_text("\x1b[")
    assert "\x1b" not in sanitize_terminal_text("\x1b")
    assert "\x1b" not in sanitize_terminal_text("Prefix\x1b[Suffix")


def test_sec_29_fuzz_sanitize_terminal_text():
    """
    SEC-29: Fuzz chuỗi ngẫu nhiên và kiểm tra ReDoS:
    - Đầu ra không chứa \x1b hay ký tự điều khiển ngoài \n, \t.
    - Không ném ngoại lệ.
    - Thời gian xử lý chuỗi 1MB (\x1b[ * 500_000) < 2.0s.
    """
    rng = random.Random(20261006)
    chars = [
        "a", "B", "1", " ", "\n", "\t", "\r", "\x00", "\x1b", "\x7f",
        "\x1b[31m", "\x1b[2J", "\x1b]0;t\x07", "\x1b\\", "[", "]", ";",
    ]

    for _ in range(200):
        length = rng.randint(10, 200)
        sample = "".join(rng.choice(chars) for _ in range(length))
        cleaned = sanitize_terminal_text(sample)

        # Kiểm tra không còn ký tự ESC
        assert "\x1b" not in cleaned
        # Kiểm tra không còn ký tự điều khiển ngoại trừ \n (10) và \t (9)
        for ch in cleaned:
            code = ord(ch)
            if code < 32 and code not in (9, 10):
                pytest.fail(f"Ký tự điều khiển còn sót: ord {code} trong {cleaned!r}")
            if code == 127:
                pytest.fail("Ký tự DEL (127) còn sót")

    # Kiểm tra ReDoS với chuỗi 1MB
    one_mb_sample = "\x1b[" * 500000
    start = time.perf_counter()
    result = sanitize_terminal_text(one_mb_sample)
    duration = time.perf_counter() - start

    assert duration < 2.0, f"Xử lý quá chậm (nguy cơ ReDoS): {duration:.2f}s"
    assert "\x1b" not in result
