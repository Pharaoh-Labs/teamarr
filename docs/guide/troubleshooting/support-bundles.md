# Support bundles and plugin channel ownership

Support-bundle schema v2 includes `owner_type` (`core` or `plugin`) for each
bounded managed event-channel record. Plugin-owned channels also carry
`plugin_id`, `plugin_logical_key`, `plugin_adoption_key`, and
`plugin_plan_generation`; core channels have null plugin fields. A stable
adoption key identifies a conceptual channel through a rename, while the
logical key identifies the current plan item. Neither channel number nor
primary stream determines ownership.

The bundle still excludes raw stream URLs, M3U account names, credentials,
tokens, plan payloads, and generic database dumps. Redaction also parses and
scrubs JSON-typed text fields recursively. Share the ZIP only after reviewing
its contents; it contains channel names, schedule metadata, and run history.

Packet 8B stores plugin ownership but does not execute plugin plans. Applying
plans, failure freeze, and plugin runtime are separate milestones.
