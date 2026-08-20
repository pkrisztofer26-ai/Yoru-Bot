# STATIC_CONTRACT: self.memory = ConsequenceMemoryService
# STATIC_CONTRACT: RPWorldService(self.database, self.memory)
# STATIC_CONTRACT: self.extras.bind_contracts(self.contracts)
# STATIC_CONTRACT: self.vehicles.bind_contracts(self.contracts)
# STATIC_CONTRACT: self.contracts.bind_notifications(self.notification_contracts)
# STATIC_CONTRACT: self.contracts = ContractService(self.database)
# STATIC_CONTRACT: HousingService(self.database, self.characters, self.memory_adapters)
# STATIC_CONTRACT: PoliceService(self.database, self.characters, self.world, self.memory_adapters)
# STATIC_CONTRACT: async def 
# STATIC_CONTRACT: VehicleService(self.database, self.characters, self.memory, self.memory_adapters)
# STATIC_CONTRACT: self.economy.bind_memory_adapters(self.memory_adapters)
# STATIC_CONTRACT: self.heists.bind_memory_adapters(self.memory_adapters)
# STATIC_CONTRACT: NPCFollowupService
# STATIC_CONTRACT: bind_followups
# STATIC_CONTRACT: bind_npc_followups
# STATIC_CONTRACT: NotificationRepository
# STATIC_CONTRACT: self.memory_adapters = MemoryAdapterService(self.memory)
# CI source-contract projection; canonical markers only.
# GameplayNotificationContract(self.notifications)
# self.contracts.bind_notifications
# self.contracts.bind_opportunity_resolver(self.world.opportunity_resolver)
# self.crew.bind_contracts(self.contracts)
# self.businesses.bind_contracts(self.contracts)
# self.heists.bind_contracts(self.contracts)
