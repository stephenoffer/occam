# Bugs

The switch for this turns on when a request reports a defect, or a check fails after work beyond a small change that didn't only touch tests.

- **A bug's cause is established:** reproduced, or input and state traced across boundaries, with a tested hypothesis. Fix the responsible component and the callers sharing the defect, where that repair is in scope, reporting the rest, instead of layering retries, catch-alls, coercions or defaults. If you can't reproduce it, label the hypothesis. After three failed fixes, or when a defect moves, question the diagnosis.
