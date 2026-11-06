# Adjustments

Surcharges and levies on top of a priced quote or invoice, such as security fees and emission zone levies.

The schedule lives in `tidewater/domain/adjustments/adjustments.toml`. Commercial edit it without a code change. Each entry names a plugin module, the lanes it applies to and the plugin's parameters. `registry.py` imports the plugin by its path when a lane matches and calls its `compute(context, params)`.

Flat fees are denominated in a currency of their own and converted into the document's currency. The `rate_source` parameter says which family of exchange rates the conversion uses. It is matched by name against the functions in the core exchange rate module, so adding a family there makes it available to the schedule.
