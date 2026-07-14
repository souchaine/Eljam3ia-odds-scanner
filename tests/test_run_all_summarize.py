from pathlib import Path
import run_all


def test_summarize_lists_per_category_codes(tmp_path):
    (tmp_path / "betslips_20260101_0000.txt").write_text(
        "Eljam3ia multiplier betslips\n\n"
        "===== CATEGORY: main =====\n"
        "BETSLIP main #1  (20 legs, combined odds x100.00)\n"
        "  >> BOOKING CODE: AAA11\n\n"
        "===== CATEGORY: corners =====\n"
        "BETSLIP corners #1  (18 legs, combined odds x90.00)\n"
        "  >> BOOKING CODE: BBB22\n\n",
        encoding="utf-8")
    out = run_all.summarize(tmp_path)
    assert "AAA11" in out
    assert "BBB22" in out


def test_summarize_lists_mixed_mode_codes(tmp_path):
    (tmp_path / "betslips_20260101_0000.txt").write_text(
        "header\n\nBETSLIP 1  (20 legs, combined odds x100.00)\n  >> BOOKING CODE: CCC33\n\n",
        encoding="utf-8")
    out = run_all.summarize(tmp_path)
    assert "CCC33" in out


def test_summarize_lists_dual_set_codes(tmp_path):
    (tmp_path / "betslips_20260101_0000.txt").write_text(
        "h\n\n===== SET A: all-odds =====\n"
        "BETSLIP A1  (20 legs, combined odds x800.00, win% 0.02)\n  >> BOOKING CODE: AA111\n\n"
        "===== SET B: 7-category diversified =====\n"
        "BETSLIP B1  (20 legs, combined odds x700.00, win% 0.03)\n  >> BOOKING CODE: BB222\n\n",
        encoding="utf-8")
    import run_all
    out = run_all.summarize(tmp_path)
    assert "AA111" in out and "BB222" in out
