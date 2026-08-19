from __future__ import annotations

OVERRIDES = {('bank_heist_plan_mismatch', 'focus_c'): {'title': 'A terv megbillen',
                                           'description': 'A helyzet nem úgy alakul, ahogy a csapat várta, ezért megállnak, és a '
                                                          'folytatásról kell dönteniük.'},
 ('bank_heist_unexpected_crowd', 'focus_b'): {'title': 'Váratlan tömeg',
                                              'description': 'A bankrablás előtt a helyszínen a vártnál nagyobb tömeg van, és a csapat nem '
                                                             'ugyanúgy látja, érdemes-e folytatni.'},
 ('store_heist_alarm_change', 'focus_a'): {'title': 'Váratlan riasztó',
                                           'description': 'Miközben a csapat egy boltrablás tervével foglalkozik, váratlanul megszólal egy '
                                                          'riasztó, ezért megállnak és döntést várnak a folytatásról.'},
 ('store_heist_alarm_change', 'focus_e'): {'title': 'Folytatás előtt',
                                           'description': 'A váratlan riasztó döntési pontot teremt a boltrablás tervében, ezért a '
                                                          'csapatnak előbb el kell döntenie, hogyan tovább.'},
 ('store_heist_teammate_panic', 'focus_d'): {'title': 'Megtorpanó kommunikáció',
                                             'description': 'Egy csapattárs pánikja miatt a csapat kommunikációja megtorpan, és '
                                                            'bizonytalanná válik a folytatás.'},
 ('crime_unknown_envelope', 'focus_c'): {'title': 'Kétes kérés',
                                         'description': 'Pénz helyett egy lezárt boríték eljuttatását kéri az ismerős, de arra nem ad '
                                                        'választ, mi van benne.'},
 ('crime_illegal_race_invite', 'focus_a'): {'title': 'Azonnali válasz',
                                            'description': 'A játékost illegális utcai autóversenyre hívják, a társaság pedig sürgeti, '
                                                           'hogy azonnal mondjon igent vagy nemet.'},
 ('crime_illegal_race_invite', 'focus_e'): {'title': 'Versenymeghívás',
                                            'description': 'Az illegális utcai autóversenyre szóló meghívásnál a társaság azonnali választ '
                                                           'kér a játékostól.'},
 ('npc_jani_mechanic', 'focus_d'): {'title': 'Későbbi egyeztetés',
                                    'description': 'Jani most csak azt szeretné tudni, hogy a játékos később vissza tud-e jönni az autó '
                                                   'állapotáról beszélni.'},
 ('npc_misi_car_dealer', 'focus_c'): {'title': 'Autókeresés mostanában',
                                      'description': 'Misi általánosságban kérdez rá, hogy a játékos nézelődik-e mostanában autó után.'},
 ('world_miskolc_roadworks', 'focus_e'): {'title': 'Belvárosi lassulás',
                                          'description': 'A miskolci útfelújítás miatt a belváros több részén lassabb a közlekedés, ami a '
                                                         'taxi- és futárjellegű munkákra is hatással van.'}}
