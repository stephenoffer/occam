# The bureau file

The bureau imports a fixed-width text file (their spec PAYIMP v2) once a week. `python -m exports bureau`
writes it from the JSON the pay run prints, so it always carries exactly what payroll worked out: regular
and overtime hours in hundredths, and basic, overtime, allowance and gross pay in pence.

Lines are 64 characters with CRLF endings: one `H` header with the week and record count, one `D` per
payslip and a `T` trailer with total gross. The bureau rejects the whole file if the trailer total doesn't
match the `D` lines, so never edit the file by hand.

Upload it on the bureau's portal by 14:00 on Tuesday.
