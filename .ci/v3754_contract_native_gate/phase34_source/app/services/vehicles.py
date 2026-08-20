# STATIC_CONTRACT: event_key=f"vehicle_repair_tx:
# STATIC_CONTRACT: event_type="vehicle_service_completed"
# STATIC_CONTRACT: record_matching_domain_event
# STATIC_CONTRACT: travel_id = int(travel_cur.lastrowid)
# STATIC_CONTRACT: record_matching_city_delivery
# STATIC_CONTRACT: async def 
# STATIC_CONTRACT:  adapter
# STATIC_CONTRACT: travel_completed
# STATIC_CONTRACT: travel_completed(
# STATIC_CONTRACT: discount_saved
# STATIC_CONTRACT: misi_dealership_discount
# STATIC_CONTRACT: active_favor_effect_tx
# STATIC_CONTRACT: consume_active_favor_effect_tx
# STATIC_CONTRACT: jani_repair_discount
from __future__ import annotations
from .vehicles_projection_support import *
from .vehicles_projection_mixin_01 import VehicleServiceProjectionMixin01
from .vehicles_projection_mixin_02 import VehicleServiceProjectionMixin02
from .vehicles_projection_mixin_03 import VehicleServiceProjectionMixin03

class VehicleService(VehicleServiceProjectionMixin01, VehicleServiceProjectionMixin02, VehicleServiceProjectionMixin03):
    """Vehicle ownership, used/dealer markets, servicing and instant city travel."""
    _VEHICLE_SELECT = 'SELECT cv.vehicle_id,cv.guild_id,cv.user_id,cv.model_key,cv.condition_key,cv.city_key,\n                                 cv.purchase_price,cv.estimated_value,cv.status,cv.acquired_at,cv.updated_at,cv.sold_at,\n                                 COALESCE(vs.is_primary,0),vs.issue_key,COALESCE(vs.issue_revealed,0),vs.last_service_at\n                          FROM character_vehicles cv\n                          LEFT JOIN vehicle_state vs ON vs.vehicle_id=cv.vehicle_id'
