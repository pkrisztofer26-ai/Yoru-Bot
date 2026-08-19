from __future__ import annotations

OVERRIDES = {('bank_heist_plan_mismatch', 'focus_a'): {'title': 'Eltérő helyzet',
                                           'description': 'A bankrablás helyzete eltér attól, amire a csapat számított, ezért röviden '
                                                          'megállnak, mert nincs egyetértés a folytatásról.'},
 ('bank_heist_plan_mismatch', 'focus_e'): {'title': 'Folytatás kérdése',
                                           'description': 'A csapat olyan eltéréssel találkozik, amire nem számított, ezért megállnak, és '
                                                          'tisztázniuk kell, hogyan tovább.'},
 ('bank_heist_unexpected_crowd', 'focus_d'): {'title': 'Zsúfolt indulás',
                                              'description': 'A helyszín már a bankrablás előtt zsúfoltabb a vártnál, ezért a csapat '
                                                             'röviden újra mérlegeli a folytatást.'},
 ('store_heist_alarm_change', 'focus_c'): {'title': 'Megbillenő terv',
                                           'description': 'A terv közben megszólaló riasztó megállítja a csapatot, ezért a folytatásról új '
                                                          'döntésre van szükség.'},
 ('store_heist_teammate_panic', 'focus_b'): {'title': 'Bizonytalan kommunikáció',
                                             'description': 'Egy csapattárs pánikja miatt a csapaton belüli kommunikáció bizonytalanná '
                                                            'válik.'},
 ('crime_unknown_envelope', 'focus_a'): {'title': 'Lezárt boríték',
                                         'description': 'Egy ismerős pénz helyett azt kéri, hogy a játékos juttasson el egy lezárt '
                                                        'borítékot, de nem mondja meg, mi van benne.'},
 ('crime_unknown_envelope', 'focus_e'): {'title': 'Eljuttatni vagy nemet mondani',
                                         'description': 'Pénz helyett egy lezárt boríték eljuttatásáról kell döntenie a játékosnak úgy, '
                                                        'hogy az ismerős nem árulja el a tartalmát.'},
 ('crime_illegal_race_invite', 'focus_c'): {'title': 'Sürgetett döntés',
                                            'description': 'Az illegális utcai autóverseny meghívásánál a társaság azonnali igen vagy nem '
                                                           'választ vár.'},
 ('npc_jani_mechanic', 'focus_b'): {'title': 'Beszélgetés az autóról',
                                    'description': 'Jani arra kíváncsi, hogy a játékos vissza tud-e jönni később az autó jelenlegi '
                                                   'állapotáról beszélni.'},
 ('npc_misi_car_dealer', 'focus_a'): {'title': 'Misi az autókról kérdez',
                                      'description': 'Misi lazán rákérdez, hogy a játékos keres-e mostanában valamilyen autót.'},
 ('npc_misi_car_dealer', 'focus_e'): {'title': 'Mostanában autó?',
                                      'description': 'Misi lazán megkérdezi, nézelődik-e mostanában autó után a játékos.'},
 ('career_mechanic_part_delay', 'focus_e'): {'title': 'Alkatrészkésés',
                                             'description': 'Az alkatrész késik, Réka pedig az autóról érdeklődik, ezért csak a jelenlegi '
                                                            'helyzet korrekt elmondása fér bele.'}}
