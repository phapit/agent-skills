import json
import os
import pytest

import injection_guard


def test_injection_corpus_metrics():
    """
    Kiểm thử tập mẫu đối kháng prompt injection (Bước 4):
    - Đọc tests/data/injection_corpus.json
    - Chạy scan_text trên toàn bộ mẫu
    - Tính toán metrics: recall theo category & tổng, FP rate, danh sách bỏ lọt và FP
    - In ra console và ghi tests/corpus_metrics.json
    - Khẳng định:
      (a) 100% mẫu expect_detect=True bị bắt.
      (b) FP = 0 trên tập benign sạch (không đánh dấu known_false_positive).
      (c) Mẫu expect_detect=False được ghi nhận và báo cáo.
      (d) Tỉ lệ bắt đúng category >= 80%.
    """
    corpus_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "injection_corpus.json"
    )
    assert os.path.isfile(corpus_file), f"Không tìm thấy file corpus: {corpus_file}"

    with open(corpus_file, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    category_stats = {}
    evasions_known = []
    false_positives = []
    caught_true_positives = 0
    expected_true_positives = 0
    correct_category_matches = 0
    clean_benign_count = 0
    clean_benign_fps = 0

    for item in corpus:
        findings = injection_guard.scan_text(item["id"], item["text"])
        detected = len(findings) > 0
        detected_categories = [f["type"] for f in findings]

        if item["label"] == "malicious":
            cat = item["category"]
            if cat not in category_stats:
                category_stats[cat] = {
                    "total": 0,
                    "expected_detect": 0,
                    "detected": 0,
                    "correct_category": 0,
                }
            category_stats[cat]["total"] += 1

            if item["expect_detect"]:
                expected_true_positives += 1
                category_stats[cat]["expected_detect"] += 1
                if detected:
                    caught_true_positives += 1
                    category_stats[cat]["detected"] += 1
                    if cat in detected_categories:
                        correct_category_matches += 1
                        category_stats[cat]["correct_category"] += 1
                else:
                    pytest.fail(f"Lọt mẫu độc hại kỳ vọng phải bắt: {item['id']} - {item['text']}")
            else:
                # Evasion đã biết
                evasions_known.append({
                    "id": item["id"],
                    "text": item["text"],
                    "category": item["category"],
                    "detected": detected,
                    "note": item.get("note", ""),
                })
        else:  # benign
            if item.get("known_false_positive", False):
                # Báo cáo mẫu benign đã biết bị bắt nhầm
                if detected:
                    false_positives.append({
                        "id": item["id"],
                        "text": item["text"],
                        "flagged_as": detected_categories,
                        "type": "known_false_positive",
                        "note": item.get("note", ""),
                    })
            else:
                clean_benign_count += 1
                if detected:
                    clean_benign_fps += 1
                    false_positives.append({
                        "id": item["id"],
                        "text": item["text"],
                        "flagged_as": detected_categories,
                        "type": "unexpected_false_positive",
                    })

    # Tính toán chỉ số tổng hợp
    overall_recall = (
        (caught_true_positives / expected_true_positives * 100)
        if expected_true_positives > 0
        else 0.0
    )
    category_accuracy = (
        (correct_category_matches / caught_true_positives * 100)
        if caught_true_positives > 0
        else 0.0
    )
    fp_rate = (
        (clean_benign_fps / clean_benign_count * 100)
        if clean_benign_count > 0
        else 0.0
    )

    metrics_output = {
        "summary": {
            "total_samples": len(corpus),
            "malicious_total": sum(s["total"] for s in category_stats.values()),
            "expected_detect_samples": expected_true_positives,
            "caught_samples": caught_true_positives,
            "overall_recall_percent": round(overall_recall, 2),
            "category_accuracy_percent": round(category_accuracy, 2),
            "clean_benign_total": clean_benign_count,
            "clean_benign_fps": clean_benign_fps,
            "false_positive_rate_percent": round(fp_rate, 2),
            "known_evasions_count": len(evasions_known),
            "known_false_positives_count": len([fp for fp in false_positives if fp["type"] == "known_false_positive"]),
        },
        "by_category": {
            cat: {
                "total": s["total"],
                "expected": s["expected_detect"],
                "detected": s["detected"],
                "recall_percent": round(s["detected"] / s["expected_detect"] * 100, 2) if s["expected_detect"] > 0 else 0,
                "category_match_percent": round(s["correct_category"] / s["detected"] * 100, 2) if s["detected"] > 0 else 0,
            }
            for cat, s in category_stats.items()
        },
        "known_evasions": evasions_known,
        "false_positives": false_positives,
    }

    # Đọc existing file nếu có để giữ lại mục 'mutation' nếu test mutation chạy trước/sau
    metrics_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_metrics.json")
    if os.path.isfile(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            if "mutation" in old_data:
                metrics_output["mutation"] = old_data["mutation"]
        except Exception:
            pass

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_output, f, indent=2, ensure_ascii=False)

    # In kết quả ra console
    print("\n" + "=" * 65)
    print("KẾT QUẢ ĐÁNH GIÁ TẬP MẪU ĐỐI KHÁNG (INJECTION CORPUS METRICS)")
    print("=" * 65)
    print(f"Tổng số mẫu kiểm thử: {len(corpus)}")
    print(f"Recall trên tập expect_detect: {overall_recall:.1f}% ({caught_true_positives}/{expected_true_positives})")
    print(f"Tỉ lệ gán đúng loại (category accuracy): {category_accuracy:.1f}% ({correct_category_matches}/{caught_true_positives})")
    print(f"False Positive Rate trên tập benign sạch: {fp_rate:.2f}% ({clean_benign_fps}/{clean_benign_count})")
    print(f"Số khoảng trống né tránh đã biết (known evasions): {len(evasions_known)}")
    print(f"Số mẫu dương tính giả đã biết (known false positives): {metrics_output['summary']['known_false_positives_count']}")
    print("=" * 65 + "\n")

    # Các khẳng định theo đặc tả:
    # (a) Mọi mẫu expect_detect=true đều bị bắt (recall = 100%)
    assert overall_recall == 100.0, f"Recall không đạt 100%: {overall_recall}%"

    # (b) Mọi mẫu benign sạch KHÔNG bị bắt (FP = 0)
    assert clean_benign_fps == 0, f"Có {clean_benign_fps} false positives trên tập benign sạch!"

    # (c) Tỉ lệ đúng loại >= 80%
    assert category_accuracy >= 80.0, f"Category accuracy không đạt 80%: {category_accuracy}%"
