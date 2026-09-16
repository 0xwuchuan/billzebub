from billzebub.imports import is_junk_shortcut_failure


def test_junk_filter_matches_shortcut_probe_failures_only() -> None:
    assert is_junk_shortcut_failure(
        status="failed",
        adapter_key="apple_wallet_shortcut",
        failure_code="invalid_payload_shape",
    )
    assert is_junk_shortcut_failure(
        status="failed",
        adapter_key="paylah_shortcut",
        failure_code="unsupported_source",
    )
    assert is_junk_shortcut_failure(
        status="failed",
        adapter_key="apple_wallet_shortcut",
        failure_code="unmapped_card",
    )
    assert is_junk_shortcut_failure(
        status="failed",
        adapter_key="apple_wallet_shortcut",
        failure_code="invalid_payload_extra",
    )
    assert not is_junk_shortcut_failure(
        status="failed",
        adapter_key="synthetic-credit",
        failure_code="account_mismatch",
    )
    assert not is_junk_shortcut_failure(
        status="accepted",
        adapter_key="apple_wallet_shortcut",
        failure_code=None,
    )
    assert not is_junk_shortcut_failure(
        status="failed",
        adapter_key="apple_wallet_shortcut",
        failure_code="missing_paylah_account",
    )
