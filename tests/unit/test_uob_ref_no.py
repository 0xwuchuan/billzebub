from billzebub.statement_adapters.uob_ref_no import (
    rewrite_uob_statement_ref_no,
    strip_uob_statement_ref_no,
)


def test_strip_trailing_ref_no_from_merchant_line() -> None:
    assert (
        strip_uob_statement_ref_no("DIN TAI FUNG-JEWEL CHANGISINGAPORE Ref No. : 12345678")
        == "DIN TAI FUNG-JEWEL CHANGISINGAPORE"
    )
    assert strip_uob_statement_ref_no("BUS/MRT RIDE Ref No.:99887766") == "BUS/MRT RIDE"
    assert strip_uob_statement_ref_no("BUS/MRT RIDE ref no. : 99887766") == "BUS/MRT RIDE"


def test_strip_leaves_absent_and_mid_string_ref_no_unchanged() -> None:
    assert strip_uob_statement_ref_no("FICTIONAL BOOKSHOP") == "FICTIONAL BOOKSHOP"
    assert strip_uob_statement_ref_no("REF NO CAFE SINGAPORE") == "REF NO CAFE SINGAPORE"
    assert (
        strip_uob_statement_ref_no("MERCHANT Ref No. : 1 MORE TEXT")
        == "MERCHANT Ref No. : 1 MORE TEXT"
    )


def test_rewrite_fails_closed_when_suffix_is_the_whole_counterparty() -> None:
    assert rewrite_uob_statement_ref_no("Ref No. : 12345") is None
    assert strip_uob_statement_ref_no("Ref No. : 12345") == "Ref No. : 12345"
