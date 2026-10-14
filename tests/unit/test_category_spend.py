from decimal import Decimal
from uuid import UUID

from billzebub.category_spend import SpendAmount, SpendCategory, assemble_category_spend
from billzebub.money import Money

FOOD = UUID("11111111-1111-4111-8111-111111111111")
DINING = UUID("22222222-2222-4222-8222-222222222222")
GROCERIES = UUID("33333333-3333-4333-8333-333333333333")
TRANSPORT = UUID("44444444-4444-4444-8444-444444444444")
LATE = UUID("55555555-5555-4555-8555-555555555555")


def _categories() -> tuple[SpendCategory, ...]:
    return (
        SpendCategory(FOOD, "Food", None),
        SpendCategory(DINING, "Dining", FOOD),
        SpendCategory(GROCERIES, "Groceries", FOOD),
        SpendCategory(TRANSPORT, "Transport", None),
        SpendCategory(LATE, "Late night", DINING),
    )


def test_parent_total_is_direct_plus_children() -> None:
    report = assemble_category_spend(
        _categories(),
        (
            SpendAmount(FOOD, Decimal("10.00"), "SGD"),
            SpendAmount(DINING, Decimal("15.00"), "SGD"),
            SpendAmount(GROCERIES, Decimal("5.00"), "SGD"),
            SpendAmount(TRANSPORT, Decimal("7.00"), "SGD"),
            SpendAmount(LATE, Decimal("2.50"), "SGD"),
        ),
        month="2026-03",
    )

    assert report.month == "2026-03"
    assert [(item.name, item.direct, item.total) for item in report.items] == [
        ("Food", Money.parse("10.00", "SGD"), Money.parse("32.50", "SGD")),
        ("Transport", Money.parse("7.00", "SGD"), Money.parse("7.00", "SGD")),
    ]
    food = report.items[0]
    assert [(child.name, child.direct, child.total) for child in food.children] == [
        ("Dining", Money.parse("17.50", "SGD"), Money.parse("17.50", "SGD")),
        ("Groceries", Money.parse("5.00", "SGD"), Money.parse("5.00", "SGD")),
    ]
    assert food.total.amount == food.direct.amount + sum(
        child.total.amount for child in food.children
    )


def test_zero_rows_and_foreign_currencies_stay_separate() -> None:
    report = assemble_category_spend(
        _categories(),
        (
            SpendAmount(DINING, Decimal("4.00"), "USD"),
            SpendAmount(FOOD, Decimal("0"), "SGD"),
            SpendAmount(UUID("66666666-6666-4666-8666-666666666666"), Decimal("9.00"), "SGD"),
        ),
        month="2026-03",
    )

    assert len(report.items) == 1
    assert report.items[0].name == "Food"
    assert report.items[0].direct == Money.parse("0", "USD")
    assert report.items[0].total == Money.parse("4.00", "USD")
    assert report.items[0].children[0].name == "Dining"
