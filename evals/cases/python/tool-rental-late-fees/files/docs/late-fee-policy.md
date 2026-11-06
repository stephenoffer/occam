# Late fee policy

- A rental is late for each business day after its due date, up to and including the day it comes back.
- Saturdays, Sundays and the holidays in `toolhire/workdays.py` are not business days. Bringing a tool back on one of those days doesn't by itself add a late day.
- The fee per late day depends on the tool class: small $3, medium $7, heavy $15.
- Late fees stop growing after 10 late days.
- Late fees and damage come out of the deposit first. We never capture more than the deposit, and what's left is released to the customer.
