from app.calculators import calculate_math


def test_basic_arithmetic() -> None:
    assert calculate_math("1 + 2")["result"] == 3
    assert calculate_math("(100 / 2.20462) * 17")["result"] > 770


def test_rejects_unsafe_input() -> None:
    bad = calculate_math("__import__('os').system('echo pwn')")
    assert "error" in bad

    bad_attr = calculate_math("os.system('rm -rf /')")
    assert "error" in bad_attr


def test_handles_div_by_zero() -> None:
    response = calculate_math("1/0")
    assert "error" in response


def test_empty_expression_returns_error() -> None:
    response = calculate_math("")
    assert "error" in response


def test_supports_unary_negation_and_pow() -> None:
    assert calculate_math("-3")["result"] == -3
    assert calculate_math("2 ** 8")["result"] == 256
