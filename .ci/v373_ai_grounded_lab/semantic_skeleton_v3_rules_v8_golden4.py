from __future__ import annotations

OVERRIDES = {('bank_heist_plan_mismatch', 'focus_d'): {'title': 'Megálló csapat',
                                           'description': 'A bankrablás során váratlanul megváltozik a helyzet, ezért a csapat röviden '
                                                          'megáll, mert nem értenek egyet a folytatásról.'},
 ('bank_heist_unexpected_crowd', 'focus_c'): {'title': 'Csapat a tömeg előtt',
                                              'description': 'A csapat a bankrablás előtt a vártnál zsúfoltabb helyszínnel találkozik, '
                                                             'ezért bizonytalanná válik a folytatás.'},
 ('store_heist_alarm_change', 'focus_b'): {'title': 'Döntés a riasztónál',
                                           'description': 'A váratlan riasztó miatt a csapat megáll, és nem folytatja automatikusan a '
                                                          'tervet, amíg nem tisztázzák, hogyan tovább.'},
 ('store_heist_teammate_panic', 'focus_a'): {'title': 'Pánik a csapatban',
                                             'description': 'A boltrablás közben az egyik csapattárs pánikba esik, és a csapat '
                                                            'kommunikációja bizonytalanná válik.'},
 ('store_heist_teammate_panic', 'focus_e'): {'title': 'Pánik miatti megállás',
                                             'description': 'Az egyik csapattárs pánikba esik, így a csapatnak előbb a kommunikációt kell '
                                                            'rendeznie, mielőtt dönt a folytatásról.'},
 ('crime_unknown_envelope', 'focus_d'): {'title': 'Boríték válasz nélkül',
                                         'description': 'Az ismerős pénz helyett egy lezárt boríték elvitelét kéri, miközben továbbra sem '
                                                        'mondja meg, mi van benne.'},
 ('crime_illegal_race_invite', 'focus_b'): {'title': 'Illegális verseny',
                                            'description': 'A társaság illegális utcai autóversenyre hívja a játékost, és rögtön választ '
                                                           'kér a részvételről.'},
 ('npc_jani_mechanic', 'focus_a'): {'title': 'Jani visszahívna',
                                    'description': 'Jani röviden megkérdezi, ráér-e a játékos később visszajönni, hogy az autó állapotáról '
                                                   'beszéljenek.'},
 ('npc_jani_mechanic', 'focus_e'): {'title': 'Jani rövid kérdése',
                                    'description': 'Jani közvetlenül rákérdez, hogy a játékos ráér-e később visszajönni az autó '
                                                   'állapotáról beszélni.'},
 ('npc_misi_car_dealer', 'focus_d'): {'title': 'Misi rövid kérdése',
                                      'description': 'Misi most csak azt szeretné tudni, hogy a játékos keres-e mostanában valamilyen '
                                                     'autót.'},
 ('memory_jani_tools', 'focus_d'): {'title': 'Jani emlékszik',
                                    'description': 'Jani röviden megemlíti, hogy a játékos korábban segített neki elpakolni a műhely előtt '
                                                   'maradt szerszámosládákat.'}}
