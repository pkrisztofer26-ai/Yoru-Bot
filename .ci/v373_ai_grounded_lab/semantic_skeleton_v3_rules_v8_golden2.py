from __future__ import annotations

OVERRIDES = {('bank_heist_plan_mismatch', 'focus_b'): {'title': 'Nincs egyetértés',
                                           'description': 'A várttól eltérő helyzet miatt a csapat megáll, és előbb közös álláspontra kell '
                                                          'jutniuk arról, hogyan tovább.'},
 ('bank_heist_unexpected_crowd', 'focus_a'): {'title': 'Zsúfoltabb helyszín',
                                              'description': 'A bankrablás előtt a helyszín a vártnál zsúfoltabb, ezért a csapaton belül '
                                                             'eltérő vélemények vannak a folytatásról.'},
 ('bank_heist_unexpected_crowd', 'focus_e'): {'title': 'Tömeg a helyszínen',
                                              'description': 'A csapat a bankrablás előtt váratlan tömeget lát a helyszínen, így a '
                                                             'folytatásról nincs azonnali egyetértés.'},
 ('store_heist_alarm_change', 'focus_d'): {'title': 'Riasztó és csapat',
                                           'description': 'A riasztó megszólalása után a csapat nem lép tovább automatikusan, hanem előbb '
                                                          'tisztázza a folytatást.'},
 ('store_heist_teammate_panic', 'focus_c'): {'title': 'Pánik miatti bizonytalanság',
                                             'description': 'Az egyik csapattárs pánikja megzavarja a csapat kommunikációját, ezért előbb '
                                                            'tisztázniuk kell a helyzetet.'},
 ('crime_unknown_envelope', 'focus_b'): {'title': 'Ismeretlen tartalom',
                                         'description': 'Az ismerős pénz helyett egy lezárt boríték elvitelére kéri a játékost, miközben '
                                                        'nem árulja el annak tartalmát.'},
 ('crime_hold_unknown_bag', 'focus_e'): {'title': 'Táska válasz nélkül',
                                         'description': 'Egy régi ismerős rövid időre egy lezárt táska megőrzését kéri, de idegesen '
                                                        'továbbra sem mondja el, mi van benne.'},
 ('crime_illegal_race_invite', 'focus_d'): {'title': 'Döntés a részvételről',
                                            'description': 'A játékosnak egy illegális utcai autóverseny meghívására kell igent vagy nemet '
                                                           'mondania, miközben a társaság sürgeti.'},
 ('npc_jani_mechanic', 'focus_c'): {'title': 'Ráérsz visszajönni?',
                                    'description': 'Az autószerelő Jani azt kérdezi, ráér-e a játékos később visszajönni az autó '
                                                   'állapotáról beszélni.'},
 ('npc_misi_car_dealer', 'focus_b'): {'title': 'Keresel most autót?',
                                      'description': 'A használt autókkal foglalkozó Misi röviden arra kíváncsi, keres-e a játékos '
                                                     'mostanában autót.'},
 ('work_mezokovesd_archive', 'focus_b'): {'title': 'Iratok rossz címke alatt',
                                          'description': 'Az irodában a mappák címkéi és a bennük lévő iratok eltérnek, így gyors pakolás '
                                                         'helyett előbb tisztázni kell a helyes besorolást.'}}
