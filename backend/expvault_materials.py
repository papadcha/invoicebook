# -*- coding: utf-8 -*-
"""
expvault_materials.py — κατάλογος υλικών του expvault (πίνακας `ylika`, στήλη `onoma`).

Γιατί υπάρχει: το expvault ταιριάζει το υλικό ΑΠΟΛΥΤΑ με το όνομα (κεφαλαία, χωρίς ασαφή
ταιριάσματα) και, αν δεν βρει, φτιάχνει ΝΕΟ υλικό — που σπάει τις νομικές κατηγορίες/αθροίσματα
αδειών. Το invoicebook αποθηκεύει περιγραφές κανονικοποιημένες προς το ιστορικό του
(`_canonicalize_description`, π.χ. «EM-EX LC-30, 65MM» αντί «EM-EX LC - 30, 65MM»), οπότε το export
αντιστοιχίζει κάθε περιγραφή στο όνομα του expvault μέσω κλειδιού (κεφαλαία, χωρίς
κενά/παύλες/σημεία στίξης).

Πηγή: expvault 1.2.0 (AppData/Roaming/expvault/expvault.db), 2026-10-01 — 29 υλικά (το ExpVault+ `v2`
ξεκινά άδειο και θα πάρει τα ονόματα του πρώτου import, άρα τα ίδια). Νέο υλικό που δεν υπάρχει εδώ
δεν χάνεται: το export το βγάζει με `.upper()` της περιγραφής και δείχνει προειδοποίηση — προσθέστε το
εδώ αφού εγκριθεί.
"""
import re

EXPVAULT_MATERIALS = (
    'EM-EX LC - 30, 65MM',
    'NONEL LP NO.20 (10 M)',
    'NONEL LP NO.25 (10 M)',
    'NONEL SNAPLINE, SL0 (15M)',
    'NONEL SNAPLINE, SL0 (30M)',
    'NONEL SNAPLINE, SL0 (4.8M)',
    'NONEL SNAPLINE, SL109 (4.8M)',
    'NONEL SNAPLINE, SL17 (4.8M)',
    'NONEL SNAPLINE, SL17 (6.0M)',
    'NONEL SNAPLINE, SL25 (4.8M)',
    'NONEL SNAPLINE, SL42 (4.8M)',
    'NONEL SNAPLINE, SL42 (6.0M)',
    'NONEL SNAPLINE, SL67 (4.8M)',
    'NONEL SNAPLINE, SL67 (6.0M)',
    'NONEL UNIDET U500 (10.2M)',
    'NONEL UNIDET U500 (12.0M)',
    'NONEL UNIDET U500 (15.0M)',
    'NONEL UNIDET U500 (18.0M)',
    'NONEL UNIDET U500 (21.0M)',
    'NONEL UNIDET U500 (30,0M)',
    'NONEL UNIDET U500 (4.8M)',
    'NONEL UNIDET U500MS (7.8M)',
    'POLADYN 31 ECO 38X380MM',
    'POLADYN 31 ECO 65X500MM',
    'ΑΚΑΡΙΑΙΑ ΘΡΥΑΛΛΙΔΑ 12GR/M PETΝ',
    'ΒΡΑΔΥΚΑΥΣΤΗ ΘΡΥΑΛΛΙΔΑ (PVC)',
    'ΗΛΕΚΤΡΙΚΟΙ ΠΥΡΟΚΡΟΤΗΤΕΣ ΝΟ.8',
    'ΚΟΙΝΟΙ ΠΥΡΟΚΡΟΤΗΤΕΣ ΝΟ.8',
    'ΠΕΤΡΑΜΜΩΝΙΤΗΣ (AN-FO)',
)


def material_key(name):
    """Κεφαλαία, μόνο γράμματα/ψηφία — κενά, παύλες, τελείες, παρενθέσεις αγνοούνται."""
    return re.sub(r'[^0-9A-ZΑ-Ω]', '', (name or '').upper())


_BY_KEY = {material_key(n): n for n in EXPVAULT_MATERIALS}


def canonical_material(description):
    """Το όνομα του expvault για την περιγραφή, ή None αν δεν υπάρχει στον κατάλογο."""
    return _BY_KEY.get(material_key(description))
