---
tags: [reach2]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

We're starting staff discounts and markdowns on the tills next week. A line in a sale needs to be able to carry a discount: an amount in pence off that line's total, with a reason of STAFF, PROMO or DAMAGED. The customer pays the discounted total, and the receipt should show each discount under its line.

At the end of the day the till's cash-up should show the total discount given for each reason, and the sales figure it reports should be net of discounts. A day with discounts has to add up just like a day without them, and sales rung before this change must still read fine.

`python -m till ring` takes a basket file. A discounted line in it will look like `{"sku": "PNT-1L-WHT", "qty": 2, "discount": {"pence": 40, "reason": "STAFF"}}`.
