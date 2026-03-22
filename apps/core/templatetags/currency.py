"""
Template filters for currency formatting.
Usage: {% load currency %} then {{ value|money }}
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """
    Format a number with dot as thousands separator.
    Examples:
        1500    → "1.500"
        25000   → "25.000"
        1234567 → "1.234.567"
        49.99   → "50"    (rounds to integer for display)
    """
    if value is None:
        return "0"
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    # Round to integer for clean display
    rounded = int(num.quantize(Decimal("1")))
    # Format with dot as thousands separator
    formatted = f"{rounded:,}".replace(",", ".")
    return formatted


@register.filter
def money_decimal(value):
    """
    Format with dot thousands and comma decimals (Colombian style).
    Examples:
        1500.50 → "1.500,50"
        25000   → "25.000,00"
    """
    if value is None:
        return "0,00"
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    # Format integer part with dot separator
    integer_part = int(num)
    decimal_part = abs(num - integer_part)
    dec_str = f"{decimal_part:.2f}"[2:]  # get "50" from "0.50"
    int_formatted = f"{integer_part:,}".replace(",", ".")
    return f"{int_formatted},{dec_str}"
