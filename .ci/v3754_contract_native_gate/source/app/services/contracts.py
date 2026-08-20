from __future__ import annotations
from app.services.contracts_models import ObjectiveSpec, ContractSnapshot, ContractDomainEventResult, ContractRecoveryReport
from app.services.contracts_core_mixin import ContractsCoreMixin
from app.services.contracts_create_mixin import ContractsCreateMixin
from app.services.contracts_event_mixin import ContractsEventMixin
from app.services.contracts_settle_mixin import ContractsSettleMixin
from app.services.contracts_recovery_mixin import ContractsRecoveryMixin

class ContractService(ContractsCoreMixin, ContractsCreateMixin, ContractsEventMixin, ContractsSettleMixin, ContractsRecoveryMixin):
    pass

__all__ = ["ObjectiveSpec","ContractSnapshot","ContractDomainEventResult","ContractRecoveryReport","ContractService"]
