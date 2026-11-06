def calculate(items, customer, coupons, tax_table, region, rounding="half_up"):
    total = 0
    for item in items:
        price = item.price * item.quantity
        if customer.vip:
            price = price * 0.9
        for coupon in coupons:
            if coupon.applies(item):
                price = price - coupon.amount
        total = total + price
    rate = tax_table[region]
    total = total + total * rate
    return round(total, 2)
