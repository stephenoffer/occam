# Partner archives

Partners export a NumPy `.npz` archive from their own systems and upload it to their SFTP inbox. There is one row per reading, sorted by station and then time.

| Key | Type | Meaning |
|---|---|---|
| `station` | unicode | Station ID. |
| `ts` | int64 | Time of the reading, epoch seconds, UTC. |
| `kwh` | float64 | Energy for the reading. A negative value is a meter reset and counts as zero, the same as in collector data. |
| `kw` | float64 | Power sample, sent instead of `kwh` by partners whose meters report power. |
| `note` | | Free text from the partner's export tool. We don't use it. |

An archive has either `kwh` or `kw`, never both.

Rollups are in kWh whichever one an archive has. For `kw`, the energy for a period is the power integrated over that period's samples with the trapezoid rule, with time in hours. Each period stands alone: the gap between the last sample of one period and the first sample of the next counts towards neither.

Periods are UTC calendar hours, days and months.
