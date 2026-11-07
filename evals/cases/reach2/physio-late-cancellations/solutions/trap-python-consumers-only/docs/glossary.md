# Glossary

**Appointment.** One booked treatment slot for one patient with one clinician.

**Session.** A block of time a clinician works on a given weekday, for example Tuesday
09:00-13:00. Slots are carved out of sessions.

**Slot.** A clinician's standard appointment length within a session, usually 45 minutes.

**Attended.** The patient came and the treatment happened (status `completed` in the app).

**DNA (did not attend).** A no-show: the patient didn't turn up and didn't tell us in
advance.

**Late cancellation.** A cancellation with less than 24 hours' notice. The slot is freed
for rebooking, but in every other way it counts as a no-show.

**Self-funded.** A patient paying for their own treatment. Insurer-funded patients'
treatment is invoiced to the insurer, outside this system.

**Charge run.** The nightly job that raises charges that have fallen due.

**Online booking deposit.** A deposit some patients pay when booking through the
website; see `patients/policy.py`.

**Clinical lead.** The senior physio at each clinic, who gets the monthly figures.
