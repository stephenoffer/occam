# Cashing up and closing the day

At the end of trading the manager on duty:

1. Counts the drawer, float included.
2. Runs the cash-up with the counted amount:

       python -m till --data /srv/till cashup --date 2026-11-09 --counted-cash 245.10

   The cash-up shows the day's sales and how many there were, sales by department, the discounts
   given by reason (staff, promotion, damaged), what came in by cash and card, change given, the
   float, and what should be in the drawer. Sales figures are after discounts. With a counted amount
   it also shows how far over or short the drawer is.
3. Investigates anything over 5.00 over or short before going further, and notes it in the
   store diary.
4. Closes the day:

       python -m till --data /srv/till close --date 2026-11-09

   A day can only be closed once. The store PC sends the closed day overnight.
5. Takes the day's sales off stock with `python -m stock --data /srv/till deplete --date ...`.

If the cash-up prints a WARNING that payments don't match sales, don't close the day: call the
store systems rota.

The card terminal has its own end-of-day; run that too, but the till doesn't read it.
