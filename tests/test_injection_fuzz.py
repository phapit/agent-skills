import json
import os
import random
import time
import pytest

import injection_guard


def test_sec_42_fuzz_scan_text_performance_and_redos():
    """
    SEC-42: Fuzz scan_text với các khối dữ liệu lớn:
    - Chuỗi lặp ký tự (1MB)
    - Base64 giả lập 1MB (kiểm tra regex [A-Za-z0-9+/]{200,})
    - Dữ liệu 100k dòng text
    - Chuỗi ngẫu nhiên dài
    Kỳ vọng: Không ném lỗi và hoàn thành < 5.0 giây mỗi ca (chống ReDoS).
    """
    # 1. Chuỗi ký tự lặp 1MB
    t0 = time.perf_counter()
    res1 = injection_guard.scan_text("fuzz_repeat", "a" * 1_000_000)
    dur1 = time.perf_counter() - t0
    assert dur1 < 5.0, f"Repeated chars took too long: {dur1:.2f}s"
    assert isinstance(res1, list)

    # 2. Base64 giả 1MB
    t0 = time.perf_counter()
    res2 = injection_guard.scan_text("fuzz_base64", "QUFB" * 250_000)
    dur2 = time.perf_counter() - t0
    assert dur2 < 5.0, f"Base64 1MB took too long: {dur2:.2f}s"
    assert len(res2) >= 1  # Bắt đúng luật base64 dài

    # 3. 100k dòng text
    t0 = time.perf_counter()
    res3 = injection_guard.scan_text("fuzz_lines", "hello world testing line\n" * 100_000)
    dur3 = time.perf_counter() - t0
    assert dur3 < 5.0, f"100k lines took too long: {dur3:.2f}s"
    assert isinstance(res3, list)

    # 4. Chuỗi ngẫu nhiên
    rng = random.Random(20261006)
    chars = [chr(i) for i in range(32, 127)] + ["\n", "\t", "\x00", "\r"]
    random_str = "".join(rng.choice(chars) for _ in range(200_000))
    t0 = time.perf_counter()
    res4 = injection_guard.scan_text("fuzz_rand", random_str)
    dur4 = time.perf_counter() - t0
    assert dur4 < 5.0, f"Random string took too long: {dur4:.2f}s"
    assert isinstance(res4, list)


def test_sec_43_mutation_adversarial_reporting():
    """
    SEC-43: Đột biến tự động (Mutation) trên các mẫu malicious expect_detect=True:
    - Đổi chữ hoa/thường lẫn lộn (case swapping).
    - Thêm khoảng trắng kép.
    - Xuống dòng chen giữa các từ.
    Thống kê và chỉ BÁO CÁO tỉ lệ còn bị bắt vào tests/corpus_metrics.json (không assert cứng).
    """
    corpus_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "injection_corpus.json"
    )
    if not os.path.isfile(corpus_file):
        pytest.skip("Corpus file not found")

    with open(corpus_file, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    target_samples = [item for item in corpus if item["label"] == "malicious" and item.get("expect_detect")]
    if not target_samples:
        pytest.skip("No target malicious samples for mutation")

    rng = random.Random(20261006)

    # Các hàm biến đổi
    def mutate_case(text: str) -> str:
        return "".join(c.upper() if rng.random() > 0.5 else c.lower() for c in text)

    def mutate_spaces(text: str) -> str:
        return text.replace(" ", "  ")

    def mutate_newlines(text: str) -> str:
        words = text.split(" ")
        # Chen \n ngẫu nhiên giữa một số từ
        return "\n".join(words[: len(words) // 2]) + " " + " ".join(words[len(words) // 2 :])

    mutators = {
        "case_swap": mutate_case,
        "double_spaces": mutate_spaces,
        "newline_split": mutate_newlines,
    }

    mutation_stats = {}

    for mut_name, mut_fn in mutators.items():
        total = len(target_samples)
        still_caught = 0
        for sample in target_samples:
            mutated_text = mut_fn(sample["text"])
            findings = injection_guard.scan_text(f"mut_{mut_name}", mutated_text)
            if len(findings) > 0:
                still_caught += 1

        retention_rate = round((still_caught / total) * 100, 2)
        mutation_stats[mut_name] = {
            "total_tested": total,
            "still_caught": still_caught,
            "retention_rate_percent": retention_rate,
        }

    overall_tested = len(target_samples) * len(mutators)
    overall_caught = sum(s["still_caught"] for s in mutation_stats.values())
    overall_rate = round((overall_caught / overall_tested) * 100, 2)

    mutation_report = {
        "overall_retention_percent": overall_rate,
        "strategies": mutation_stats,
    }

    # Cập nhật vào corpus_metrics.json
    metrics_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_metrics.json")
    metrics_data = {}
    if os.path.isfile(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics_data = json.load(f)
        except Exception:
            metrics_data = {}

    metrics_data["mutation"] = mutation_report

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_data, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print("KẾT QUẢ ĐỘT BIẾN ĐỐI KHÁNG (MUTATION ROBUSTNESS REPORT)")
    print("=" * 65)
    for name, st in mutation_stats.items():
        print(f"Chiến lược {name:15}: bắt lại {st['still_caught']}/{st['total_tested']} ({st['retention_rate_percent']}%)")
    print(f"Tỉ lệ giữ nguyên khả năng phát hiện: {overall_rate}%")
    print("=" * 65 + "\n")
