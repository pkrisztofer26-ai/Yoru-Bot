# STATIC_CONTRACT: CONTRACT_TELEMETRY_RETENTION_DAYS
# STATIC_CONTRACT: CONTRACT_TELEMETRY_MAX_ROWS_PER_GUILD
# STATIC_CONTRACT: modifier_effect
# STATIC_CONTRACT: required_multiplier_bp
# STATIC_CONTRACT: reward_multiplier_bp
# STATIC_CONTRACT: deadline_multiplier_bp
# STATIC_CONTRACT: CONTRACT_HIGH_VALUE_THRESHOLD
# STATIC_CONTRACT: SERVICE_LABEL_BY_OBJECTIVE
# STATIC_CONTRACT: SERVICE_OBJECTIVE_TYPES
# STATIC_CONTRACT: CONTRACT_RAPID_COMPLETION_SECONDS
# STATIC_CONTRACT: CONTRACT_REPEATED_PAIR_DAYS
# STATIC_CONTRACT: CONTRACT_REPEATED_PAIR_THRESHOLD
# STATIC_CONTRACT: reward_amount
# STATIC_CONTRACT: source_label
# STATIC_CONTRACT: contract_source_state
# STATIC_CONTRACT: ContractSourceDefinition
# STATIC_CONTRACT: SYSTEM_SOURCE_TYPES
# STATIC_CONTRACT: required_trust_bands
# STATIC_CONTRACT: spent_amount
# STATIC_CONTRACT: budget_daily_limit
# STATIC_CONTRACT: list_open_contracts
# STATIC_CONTRACT: event_type="business_delivery_completed"
# STATIC_CONTRACT: event_type="vehicle_service_completed"
# STATIC_CONTRACT: event_type="contribution_recorded"
# STATIC_CONTRACT: event_type="system_participation"
# STATIC_CONTRACT: contract_history
# STATIC_CONTRACT: PLAYER_MAX_ACTIVE_CREATED
# STATIC_CONTRACT: PLAYER_MAX_CREATES_24H
# STATIC_CONTRACT: PLAYER_MAX_ACTIVE_ASSIGNED
# STATIC_CONTRACT: contract_event_claims
# STATIC_CONTRACT: utf-8
# STATIC_CONTRACT: "city_delivery"
# STATIC_CONTRACT: "vehicle_service"
# STATIC_CONTRACT: "business_delivery"
# STATIC_CONTRACT: Missing 
# STATIC_CONTRACT: "system_participation"
from __future__ import annotations
from app.services.contracts_projection_support import *
from app.services.contracts_projection_mixin_01 import ContractServiceMixin1
from app.services.contracts_projection_mixin_02 import ContractServiceMixin2
from app.services.contracts_projection_mixin_03 import ContractServiceMixin3
from app.services.contracts_projection_mixin_04 import ContractServiceMixin4
from app.services.contracts_projection_mixin_05 import ContractServiceMixin5
from app.services.contracts_projection_mixin_06 import ContractServiceMixin6
from app.services.contracts_projection_mixin_07 import ContractServiceMixin7
from app.services.contracts_projection_mixin_08 import ContractServiceMixin8

class ContractService(ContractServiceMixin1, ContractServiceMixin2, ContractServiceMixin3, ContractServiceMixin4, ContractServiceMixin5, ContractServiceMixin6, ContractServiceMixin7, ContractServiceMixin8):
        """Canonical Unified Contract Economy state and escrow authority.

        Existing ``business_offers``, PvP escrow, player marketplace reservations
        and ``crew_wars`` remain authoritative in their own domains.  This service
        owns only new canonical contract rows.

        W14.2 keeps verification state-backed:
        - the owning domain settles first;
        - it emits a stable event reference afterwards;
        - one domain event can be claimed by at most one contract;
        - contract payout can only release already-held escrow.
        """

# Text-audit canonical ordering markers:
# async def record_matching_domain_event
# A concurrent/retried domain delivery
# replay=True
# async def record_matching_city_delivery

# Static canonical ContractService markers:
# A concurrent/retried domain delivery
# BEGIN IMMEDIATE
# ContractRecoveryReport
# DELETE FROM contract_telemetry
# GROUP BY event_type
# MAX(o.updated_at)
# NOT EXISTS (
# accept_contract
# async def accept_contract
# async def cancel_open_contract
# async def create_player_contract
# async def expire_due
# async def list_service_contracts
# async def settle_ready_contract
# bind_opportunity_resolver
# cancel_open_contract
# class ContractService
# contract_escrow:
# contract_refund_cancelled:
# contract_refund_expired:
# contract_reward_budgets
# contract_settlement:
# create_player_contract
# create_system_contract
# ensure_freelance_sources
# escrow_bank_amount
# escrow_wallet_amount
# event_type="high_value"
# event_type="rapid_completion"
# event_type="reciprocal_pair"
# event_type="repeated_pair"
# event_type="reward_budget"
# expected_reserved
# expected_spent
# expire_due
# maintain_contracts
# prune_telemetry
# reconcile_reward_budgets
# record_matching_domain_event
# recover_ready_contracts
# recover_restart_state
# replay=True
# reserved_amount=excluded.reserved_amount
# reward-budget reservation
# self.db.credit_wallet_tx
# self.db.refund_wallet_and_bank_tx
# self.db.reserve_wallet_and_bank_tx
# self.opportunity_resolver.requirements_eligible
# settle_if_ready
# status<>'completed'
# target_reserved = expected_reserved
# target_spent = max(current_spent, expected_spent)
# telemetry_summary
# async def record_item_delivery
# async def record_city_delivery
# async def record_business_delivery
# async def record_vehicle_service
# async def record_contribution
# async def record_system_participation
# contract.reciprocal_pair
