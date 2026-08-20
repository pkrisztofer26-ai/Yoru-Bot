# STATIC_CONTRACT: opportunity_key=opportunity_key
# STATIC_CONTRACT: add_item(
# STATIC_CONTRACT: result.effect_label
# STATIC_CONTRACT: add_item
# STATIC_CONTRACT: record_opportunity_outcome
# STATIC_CONTRACT: action_key.startswith("favor:")
# STATIC_CONTRACT: action_key.startswith("relationship:tension:")
# STATIC_CONTRACT: action_key.startswith("relationship:rival:")
# STATIC_CONTRACT: source_family=source_family
# STATIC_CONTRACT: source_family: str | None = None
# CI source-contract projection; canonical markers only.
# record_opportunity_selection
# action_key.startswith("contract:")
