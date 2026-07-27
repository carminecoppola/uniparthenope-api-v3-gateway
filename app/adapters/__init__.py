"""Adapter verso i sistemi esterni.

Interfaccia comune (duck typing) implementata da MockEsse3Adapter e Esse3Adapter:

- login(...)                          -> (profile: dict, careers: list[Career])
- get_plan(career_id)                 -> (list[PlanEntry], skipped: int)
- get_exam_sessions(career, ad_id=)   -> (list[ExamSession], skipped: int)
- book_exam(career, app_id, ad_id, adsce_id) -> dict
- get_reservations(career)            -> (list[Reservation], skipped: int)
- delete_reservation(career, reservation_id) -> bool  # False = già assente
- get_photo(kind, ref)                -> bytes         # NotFound se assente
- bus_routes() / dining_menus(date=)  -> list
- register_device(username, token, platform) / unregister_device(token)
"""
