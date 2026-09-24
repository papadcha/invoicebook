# -*- coding: utf-8 -*-
"""
backup.py — Τήρηση αντιγράφων ασφαλείας για invoicebook.db + pdf_store.

Port από το αδερφό project C:\\expvault (backend/backup.py) — εκεί ήδη λυμένο και
δουλεμένο πρόβλημα (timestamped snapshots + keep-last-N pruning, ενιαία λογική για
τοπικό φάκελο ΚΑΙ rclone remote, restore με SQLite integrity_check). Η μόνη ουσιαστική
προσθήκη εδώ είναι το pdf_store κομμάτι (_backup_pdf_store) — το expvault δεν έχει
αντίστοιχο μεγάλο φάκελο εγγράφων να προστατέψει, μόνο το δικό του .db αρχείο.

DB_PATH/PDF_STORE_DIR/DATA_DIR ορίζονται δυναμικά από το bridge.py μετά το import,
ίδιο μοτίβο με το db.DB_NAME/db.PDF_STORE_DIR του domain_invoices module.
"""
import gzip
import os
import shutil
import json
import re
import subprocess
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

DB_PATH = None         # ορίζεται από bridge.py -- invoicebook.db path
PDF_STORE_DIR = None   # ορίζεται από bridge.py -- ίδιο pdf_store με το database.py
DATA_DIR = None        # ορίζεται από bridge.py -- πού ζει το backup_config.json

TIMESTAMP_FMT = '%Y%m%d_%H%M%S'
PREFIX = 'invoicebook_backup_'
EXT = '.db'
# Τα νέα αντίγραφα ανεβαίνουν συμπιεσμένα (.db.gz) — η βάση συμπιέζεται στο ~1/6
# (8,4 → 1,4 MB) σε ~0,1″, και στο αργό/ασταθές Mega το ανέβασμα έπεσε τυπικά από ~30″
# σε ~8″ (μέτρηση 2026-09-23, 4 επαναλήψεις). Τα παλιά .db αντίγραφα μένουν έγκυρα:
# εμφανίζονται, μετράνε στο keep-last-N και γίνονται restore κανονικά.
GZ_EXT = '.db.gz'
BACKUP_EXTS = (GZ_EXT, EXT)

# Ξεχωριστό, λιγότερο συχνό πλήρες αρχείο pdf_store (βλ. section πιο κάτω) --
# συμπληρώνει το προσθετικό _backup_pdf_store, δεν το αντικαθιστά.
PDF_ARCHIVE_PREFIX = 'pdf_store_archive_'
PDF_ARCHIVE_EXT = '.zip'
PDF_ARCHIVE_SUBDIR = 'pdf_store_archives'
PDF_ARCHIVE_KEEP = 4        # ~ένας μήνας κάλυψης σε εβδομαδιαίο ρυθμό, όχι το max_keep=20 της βάσης (24GB/προορισμό θα ήταν υπερβολικό)
PDF_ARCHIVE_MIN_DAYS = 7

# rclone είναι ήδη εγκατεστημένο system-wide σε αυτό το μηχάνημα (χρησιμοποιείται ήδη
# από το expvault, με δύο έτοιμα remotes: mega:/gdrive:) -- δεν χρειάζεται bundling.
RCLONE_BIN = os.environ.get('INTAKE_TOOL_RCLONE_PATH') or 'rclone'


def _config_path():
    return Path(DATA_DIR) / 'backup_config.json'


def _load():
    p = _config_path()
    if p.exists():
        content = p.read_text(encoding='utf-8').strip()
        if content:
            return json.loads(content)
    return {'paths': [], 'max_keep': 20, 'last_backup': '', 'last_status': ''}


def _save(cfg):
    _config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


def _is_rclone(path: str) -> bool:
    # rclone remotes μοιάζουν με "remote:some/path" -- πρέπει να έχουν ':' αλλά να μην
    # ξεκινάνε με '/'. Τα Windows paths (C:\..., C:/..., ή UNC \\NAS\share) ΔΕΝ πρέπει
    # να μπερδεύονται με rclone remote -- αποκλείονται πρώτα ρητά (ίδιο σκεπτικό/bug-
    # πρόληψη με το expvault's αντίστοιχο).
    if re.match(r'^[A-Za-z]:[\\/]', path) or path.startswith('\\\\'):
        return False
    return ':' in path and not path.startswith('/')


def get_config():
    return _load()


def save_config(paths: list, max_keep: int = 20):
    try:
        max_keep = int(max_keep)
    except (TypeError, ValueError):
        max_keep = 20
    max_keep = max(1, min(max_keep, 365))

    cfg = _load()
    cfg['paths'] = [p for p in paths if p]
    cfg['max_keep'] = max_keep
    _save(cfg)
    return cfg


def list_rclone_remotes() -> list:
    try:
        r = subprocess.run([RCLONE_BIN, 'listremotes'], capture_output=True, text=True, timeout=10)
        return [x.strip() for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        return []


def list_remotes_detail() -> list:
    import configparser, sys
    candidates = [Path.home() / '.config' / 'rclone' / 'rclone.conf']
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            candidates.insert(0, Path(appdata) / 'rclone' / 'rclone.conf')
    conf_path = next((p for p in candidates if p.exists()), None)
    if conf_path is None:
        return []
    cfg = configparser.ConfigParser()
    cfg.read(str(conf_path))
    result = []
    for name in cfg.sections():
        result.append({
            'name': name,
            'remote': name + ':',
            'type': cfg[name].get('type', '?'),
            'provider': cfg[name].get('provider', ''),
        })
    return result


def delete_remote(name: str) -> dict:
    try:
        r = subprocess.run(
            [RCLONE_BIN, 'config', 'delete', name],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return {'ok': False, 'error': r.stderr.strip() or r.stdout.strip()}
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── DB backup: timestamped snapshots + keep-last-N (τοπικό ή rclone) ──────────

def _dest_name(ts: str, reason: str = None) -> str:
    return f'{PREFIX}{ts}_{reason}{GZ_EXT}' if reason else f'{PREFIX}{ts}{GZ_EXT}'


def _local_backup_files(p: Path) -> list:
    return [f for ext in BACKUP_EXTS for f in p.glob(f'{PREFIX}*{ext}')]


def _rclone_include_args() -> list:
    return [arg for ext in BACKUP_EXTS for arg in ('--include', f'{PREFIX}*{ext}')]


def _make_compressed_snapshot() -> str:
    """Συνεπές στιγμιότυπο της βάσης (SQLite backup API — όχι raw αντιγραφή αρχείου,
    που θα μπορούσε να πιάσει μισογραμμένη σελίδα αν γινόταν εγγραφή εκείνη τη στιγμή),
    συμπιεσμένο σε προσωρινό .db.gz. Ο caller σβήνει το αρχείο."""
    fd, raw_tmp = tempfile.mkstemp(suffix=EXT)
    os.close(fd)
    fd, gz_tmp = tempfile.mkstemp(suffix=GZ_EXT)
    os.close(fd)
    try:
        src = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
        dst = sqlite3.connect(raw_tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(raw_tmp, 'rb') as fin, gzip.open(gz_tmp, 'wb', compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        return gz_tmp
    except Exception:
        try:
            os.unlink(gz_tmp)
        except OSError:
            pass
        raise
    finally:
        try:
            os.unlink(raw_tmp)
        except OSError:
            pass


def _do_local_backup(folder: str, max_keep: int, reason: str = None) -> dict:
    p = Path(folder)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': folder}

    ts = datetime.now().strftime(TIMESTAMP_FMT)
    dest = p / _dest_name(ts, reason)
    snapshot = None
    try:
        snapshot = _make_compressed_snapshot()
        shutil.copyfile(snapshot, dest)
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': folder}
    finally:
        if snapshot:
            try:
                os.unlink(snapshot)
            except OSError:
                pass

    backups = sorted(_local_backup_files(p), key=lambda f: f.name)
    for old in backups[:-max_keep]:
        try:
            old.unlink()
        except Exception:
            pass

    return {'ok': True, 'path': str(dest), 'folder': folder}


def _list_local_backups(folder: str) -> list:
    p = Path(folder)
    if not p.exists():
        return []
    result = []
    for f in sorted(_local_backup_files(p), key=lambda f: f.name, reverse=True):
        m = re.search(r'(\d{8}_\d{6})', f.name)
        if m:
            ts = datetime.strptime(m.group(1), TIMESTAMP_FMT)
            result.append({
                'name': f.name, 'path': str(f),
                'ts': ts.strftime('%d/%m/%Y %H:%M:%S'),
                'size_kb': round(f.stat().st_size / 1024, 1),
            })
    return result


def _do_rclone_backup(remote: str, max_keep: int, reason: str = None) -> dict:
    ts = datetime.now().strftime(TIMESTAMP_FMT)
    dest = f"{remote.rstrip('/')}/{_dest_name(ts, reason)}"
    snapshot = None
    try:
        snapshot = _make_compressed_snapshot()
        r = subprocess.run(
            [RCLONE_BIN, 'copyto', snapshot, dest],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode != 0:
            return {'ok': False, 'error': r.stderr.strip() or r.stdout.strip(), 'folder': remote}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Timeout (120s)', 'folder': remote}
    except FileNotFoundError:
        return {'ok': False, 'error': 'rclone δεν βρέθηκε στο σύστημα', 'folder': remote}
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': remote}
    finally:
        if snapshot:
            try:
                os.unlink(snapshot)
            except OSError:
                pass

    # Μερικά rclone backends (επιβεβαιωμένο με Mega στη δοκιμή αυτής της λειτουργίας,
    # 2026-09-07 -- ένα ανεβασμένο αρχείο εμφανίστηκε στο lsjson ~12 δευτερόλεπτα
    # αργότερα απ' ό,τι το ίδιο το copyto ανέφερε επιτυχία) δεν δείχνουν αμέσως ένα
    # μόλις ανεβασμένο αρχείο. Αν το pruning βασιστεί σε μια τέτοια ημιτελή λίστα,
    # σβήνει περισσότερα απ' όσα πρέπει (over-pruning, όχι απλά αποτυχία pruning) --
    # έτσι χάθηκε ένα αντίγραφο στη δοκιμή παρότι υπήρχε ήδη ένα retry με μικρότερο
    # timeout. Retry με μεγαλύτερη υπομονή μέχρι να δούμε το ίδιο το αρχείο που μόλις
    # ανεβάσαμε μέσα στη λίστα· αν ΠΟΤΕ δεν εμφανιστεί μέσα στο παράθυρο αναμονής,
    # παραλείπεται εντελώς το pruning αυτού του γύρου (ασφαλέστερο να μείνει
    # προσωρινά ένα παραπάνω αντίγραφο παρά να σβηστεί κάτι που ίσως δεν έχει καν
    # καταγραφεί ακόμα στη λίστα).
    just_uploaded = _dest_name(ts, reason)
    try:
        files = []
        seen_upload = False
        for attempt in range(6):
            ls = subprocess.run(
                [RCLONE_BIN, 'lsjson', remote, *_rclone_include_args()],
                capture_output=True, text=True, timeout=60
            )
            if ls.returncode != 0:
                break
            files = json.loads(ls.stdout or '[]')
            if any(f['Name'] == just_uploaded for f in files):
                seen_upload = True
                break
            time.sleep(5)
        if seen_upload:
            files = sorted(files, key=lambda x: x['Name'])
            for old in files[:-max_keep]:
                subprocess.run(
                    [RCLONE_BIN, 'deletefile', f"{remote.rstrip('/')}/{old['Name']}"],
                    capture_output=True, timeout=30
                )
    except Exception:
        pass

    return {'ok': True, 'path': dest, 'folder': remote}


def _list_rclone_backups(remote: str) -> list:
    try:
        r = subprocess.run(
            [RCLONE_BIN, 'lsjson', remote, *_rclone_include_args()],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            return []
        files = sorted(json.loads(r.stdout or '[]'), key=lambda x: x['Name'], reverse=True)
        result = []
        for f in files:
            m = re.search(r'(\d{8}_\d{6})', f['Name'])
            if m:
                ts = datetime.strptime(m.group(1), TIMESTAMP_FMT)
                result.append({
                    'name': f['Name'], 'path': f"{remote.rstrip('/')}/{f['Name']}",
                    'ts': ts.strftime('%d/%m/%Y %H:%M:%S'),
                    'size_kb': round(f.get('Size', 0) / 1024, 1),
                })
        return result
    except Exception:
        return []


def do_backup(folder: str, max_keep: int = 20, reason: str = None) -> dict:
    # Ίδιος γρήγορος reachability έλεγχος (~15s max για rclone remotes) με το
    # _backup_pdf_store/_do_pdf_archive παρακάτω -- χωρίς αυτόν, ένας μη προσβάσιμος
    # προορισμός θα περίμενε το πλήρες 120s timeout του _do_rclone_backup's copyto πριν
    # αποτύχει, αντί για γρήγορη αποτυχία. Σκόπιμη ασυμμετρία: ΔΕΝ υπάρχει reachability
    # gate πριν από αυτό σε καμία άλλη κλήση -- μόνο εδώ, ώστε ένας πραγματικά αργός
    # ΑΛΛΑ προσβάσιμος προορισμός (π.χ. πρώτο sync χιλιάδων αρχείων) να ΜΗΝ κοπεί ποτέ
    # τεχνητά, μόνο ένας όντως απρόσιτος να αποτύχει γρήγορα.
    try:
        _check_reachable(folder)
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': folder}
    if _is_rclone(folder):
        return _do_rclone_backup(folder, max_keep, reason)
    return _do_local_backup(folder, max_keep, reason)


def _check_reachable(folder: str):
    """Ρίχνει σαφές exception αν ο προορισμός δεν είναι προσβάσιμος ΤΩΡΑ (π.χ. NAS/
    δίσκος αποσυνδεδεμένος) -- μόνο για τις listing κλήσεις που τροφοδοτούν το UI
    (list_backups/list_pdf_archives παρακάτω). Οι εσωτερικές _list_local_backups/
    _list_pdf_archives ΔΕΝ αλλάζουν και συνεχίζουν να επιστρέφουν σιωπηλά [] σε αυτή
    την περίπτωση -- τις χρησιμοποιεί και η ίδια η λογική backup/staleness-gate
    (_should_run_pdf_archive), όπου ένα προσωρινά απρόσιτο NAS δεν πρέπει να ρίξει
    exception που θα σταματούσε το backup των ΥΠΟΛΟΙΠΩΝ προορισμών.

    Πριν αυτό, ένα απρόσιτο NAS έκανε το list_backups/list_pdf_archives να επιστρέψει
    σιωπηλά [] -- η ουρά έδειχνε ίδιο μήνυμα με "δεν υπάρχουν αντίγραφα ακόμα" σε
    πρωτόγνωρο προορισμό, χωρίς καμία ένδειξη ότι κάτι πραγματικά δεν δουλεύει."""
    if _is_rclone(folder):
        # Ελέγχουμε το remote ΡΙΖΑ (π.χ. "pcloud:"), όχι ολόκληρο το folder με τον
        # υποφάκελο -- lsd σε υποφάκελο που δεν έχει δημιουργηθεί ακόμα (π.χ. πρώτο
        # backup σε νέο "-dev" προορισμό) επιστρέφει ίδιο "directory not found" με
        # πραγματικά απρόσιτο remote, και θα μπλόκαρε ΜΟΝΙΜΑ κάθε backup εκεί -- το
        # copyto που θα τον δημιουργούσε ποτέ δεν προλαβαίνει να τρέξει. Αρκεί το ίδιο
        # το remote να απαντάει· αν λείπει μόνο ο υποφάκελος, το copyto τον φτιάχνει.
        remote_root = folder.split(':', 1)[0] + ':'
        try:
            r = subprocess.run([RCLONE_BIN, 'lsd', remote_root], capture_output=True, text=True, timeout=15)
        except Exception as e:
            raise RuntimeError(f'Το remote "{folder}" δεν είναι προσβάσιμο: {e}')
        if r.returncode != 0:
            raise RuntimeError(f'Το remote "{folder}" δεν είναι προσβάσιμο: {r.stderr.strip() or r.stdout.strip()}')
    elif not Path(folder).exists():
        raise FileNotFoundError(f'Ο φάκελος "{folder}" δεν βρέθηκε — δίσκος/NAS συνδεδεμένος;')


def list_backups(folder: str) -> list:
    _check_reachable(folder)
    if _is_rclone(folder):
        return _list_rclone_backups(folder)
    return _list_local_backups(folder)


def _rclone_remote_provider(remote_name: str) -> str:
    """Type ('drive', 'mega', ...) ενός ρυθμισμένου rclone remote, διαβάζοντας
    απευθείας το rclone.conf -- μόνο για να αποφύγουμε γνωστά per-backend quirks
    (π.χ. Google Drive πολύ αργό σε χιλιάδες μικρά αρχεία, δες _backup_pdf_store
    παρακάτω), όχι γενικής χρήσης introspection."""
    import configparser
    candidates = [Path.home() / '.config' / 'rclone' / 'rclone.conf']
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            candidates.insert(0, Path(appdata) / 'rclone' / 'rclone.conf')
    conf_path = next((p for p in candidates if p.exists()), None)
    if conf_path is None:
        return ''
    cfg = configparser.ConfigParser()
    cfg.read(str(conf_path))
    return cfg[remote_name].get('type', '') if remote_name in cfg else ''


# ── Staleness-gate: πλήρης παράλειψη backup ανά προορισμό όταν τίποτα δεν άλλαξε ──
# Φτηνός τοπικός έλεγχος (mtime της βάσης + fingerprint του pdf_store, όχι καμία κλήση
# δικτύου/rclone) πριν καν αγγιχτεί ο προορισμός -- αν το ίδιο fingerprint ήδη
# αντιγράφηκε επιτυχώς εκεί την προηγούμενη φορά, παραλείπεται ΟΛΟΚΛΗΡΟ το backup
# (DB + mirror + pdf_archive-check) γι' αυτόν τον προορισμό. Ίδιο πνεύμα με το ήδη
# υπάρχον 7ήμερο staleness-gate του pdf_archive, αλλά content-based αντί για χρονικό.
# Ανά προορισμό (όχι global) ώστε ένας προσωρινά offline προορισμός (π.χ. κοιμισμένο
# NAS) να ξαναδοκιμάζεται στο επόμενο κλείσιμο ακόμα κι αν τίποτα άλλο δεν άλλαξε.

def _pdf_store_fingerprint() -> dict:
    if not PDF_STORE_DIR or not os.path.isdir(PDF_STORE_DIR):
        return {'count': 0, 'mtime': 0}
    count = 0
    max_mtime = 0.0
    with os.scandir(PDF_STORE_DIR) as it:
        for entry in it:
            if entry.is_file():
                count += 1
                m = entry.stat().st_mtime
                if m > max_mtime:
                    max_mtime = m
    return {'count': count, 'mtime': max_mtime}


def _current_state() -> dict:
    db_mtime = os.path.getmtime(DB_PATH) if DB_PATH and os.path.exists(DB_PATH) else 0
    pdf = _pdf_store_fingerprint()
    return {'db_mtime': db_mtime, 'pdf_count': pdf['count'], 'pdf_mtime': pdf['mtime']}


def _unchanged_since_last_ok(folder: str, dest_state: dict, current: dict) -> bool:
    prev = dest_state.get(folder)
    if not prev or not prev.get('ok'):
        return False
    return (prev.get('db_mtime') == current['db_mtime']
            and prev.get('pdf_count') == current['pdf_count']
            and prev.get('pdf_mtime') == current['pdf_mtime'])


# ── pdf_store backup: προσθετικό mirror, ΧΩΡΙΣ pruning (τα PDF δεν λήγουν) ────
# rclone copy (όχι sync/--delete) -- ποτέ δεν σβήνει στον προορισμό κάτι που τυχόν
# λείπει πια από το ζωντανό pdf_store· δουλεύει ενιαία είτε ο προορισμός είναι
# τοπικό/NAS path είτε πραγματικό rclone remote (το rclone έχει δικό του local
# filesystem backend) -- δεν χρειάζεται ξεχωριστός κώδικας robocopy.
#
# Γνωστός περιορισμός, επιβεβαιώθηκε 2026-09-16 στην πράξη (προσθήκη gdrive: σαν
# προορισμό): το Google Drive API έχει τεράστιο overhead ανά αρχείο -- σε δοκιμή με
# 2740 υπάρχοντα PDF, ρυθμός μόλις ~2 αρχεία/8 δευτ. (~3+ ώρες συνολικά), θα σκάγανε
# μακράν πριν το 30λεπτο timeout παρακάτω. Το Mega (ίδιο μέγεθος δεδομένων) τελείωσε
# σχεδόν αμέσως, άρα δεν είναι γενικό πρόβλημα rclone/δικτύου, ειδικά του Drive
# backend σε πολλά μικρά αρχεία. Παραλείπεται εντελώς για gdrive-τύπου remotes εδώ
# (το invoicebook.db backup παρακάτω ΔΕΝ επηρεάζεται -- ένα αρχείο, γρήγορο παντού· το
# ίδιο και το ενιαίο pdf_store_archive zip πιο κάτω, μονο-αρχείο upload, όχι
# χιλιάδες-μικρά-αρχεία πρόβλημα).

def _backup_pdf_store(dest_root: str) -> dict:
    if not PDF_STORE_DIR or not os.path.isdir(PDF_STORE_DIR):
        return {'ok': True, 'skipped': 'no pdf_store', 'folder': dest_root}
    # Φτηνός reachability έλεγχος ΠΡΙΝ το rclone copy -- χωρίς αυτό, ένα μη προσβάσιμο
    # τοπικό/NAS path (π.χ. αποσυνδεδεμένος δίσκος) κάνει το rclone να αποτυγχάνει σε
    # ΚΑΘΕ ένα από τα ~2740 αρχεία, 3 πλήρεις φορές (retry ολόκληρου του copy, default
    # rclone behavior) -- 8220+ γραμμές σφάλματος για μία μόνο αποτυχημένη προσπάθεια.
    # Επιβεβαιώθηκε στην πράξη 2026-09-17 (πραγματικό κλείσιμο με το Z:\ αποσυνδεδεμένο).
    # Ίδιο _check_reachable() με τα list_backups/list_pdf_archives -- εδώ πιάνουμε το
    # exception αντί να το αφήσουμε να ανέβει, ώστε ένας offline προορισμός να μη
    # σταματήσει το backup των υπόλοιπων (ίδιο invariant με τον staleness-gate loop).
    try:
        _check_reachable(dest_root)
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': dest_root}
    if _is_rclone(dest_root) and _rclone_remote_provider(dest_root.split(':', 1)[0]) == 'drive':
        return {
            'ok': True,
            'skipped': 'Google Drive: το προσθετικό pdf_store mirror (χιλιάδες μικρά αρχεία) '
                       'παραλείπεται λόγω πολύ αργού upload στο Drive API (~3+ ώρες, δοκιμάστηκε '
                       '2026-09-16) -- πλήρης κάλυψη pdf_store σε αυτόν τον προορισμό γίνεται μέσω '
                       'του pdf_store_archive (ενιαίο zip) παρακάτω.',
            'folder': dest_root,
        }
    dest = f"{dest_root.rstrip('/')}/pdf_store" if _is_rclone(dest_root) \
        else str(Path(dest_root) / 'pdf_store')
    try:
        r = subprocess.run(
            [RCLONE_BIN, 'copy', str(PDF_STORE_DIR), dest, '--create-empty-src-dirs'],
            capture_output=True, text=True, timeout=1800
        )
        if r.returncode != 0:
            return {'ok': False, 'error': r.stderr.strip() or r.stdout.strip(), 'folder': dest_root}
        return {'ok': True, 'path': dest, 'folder': dest_root}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Timeout (30 λεπτά) στο αντίγραφο pdf_store', 'folder': dest_root}
    except FileNotFoundError:
        return {'ok': False, 'error': 'rclone δεν βρέθηκε στο σύστημα', 'folder': dest_root}
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': dest_root}


# ── pdf_store πλήρες συμπιεσμένο αρχείο (ξεχωριστό, λιγότερο συχνό) ───────────
# Το προσθετικό mirror παραπάνω λύνει το "συχνό backup" σωστά, αλλά μια πλήρης
# επαναφορά θα σήμαινε τράβηγμα χιλιάδων ξεχωριστών αρχείων ένα-ένα -- αργό πάνω από
# NAS/δίκτυο (επιβεβαιωμένο στην πράξη). Εδώ φτιάχνεται ΕΝΑ zip όλου του pdf_store,
# λιγότερο συχνά (staleness gate, όχι πραγματικός scheduler -- δεν υπάρχει κανένας
# στο app σήμερα), ειδικά για γρήγορη πλήρη ανάκτηση σε έκτακτη ανάγκη.
# ZIP_STORED (όχι DEFLATED): τα PDF είναι ήδη εσωτερικά συμπιεσμένα (JPEG/CCITT) --
# re-compression θα κόστιζε χρόνο/CPU για σχεδόν μηδενικό όφελος χώρου.

def _list_pdf_archives(folder: str) -> list:
    if _is_rclone(folder):
        remote_dir = f"{folder.rstrip('/')}/{PDF_ARCHIVE_SUBDIR}"
        try:
            r = subprocess.run(
                [RCLONE_BIN, 'lsjson', remote_dir, '--include', f'{PDF_ARCHIVE_PREFIX}*{PDF_ARCHIVE_EXT}'],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode != 0:
                return []
            files = sorted(json.loads(r.stdout or '[]'), key=lambda x: x['Name'], reverse=True)
        except Exception:
            return []
        result = []
        for f in files:
            m = re.search(r'(\d{8}_\d{6})', f['Name'])
            if m:
                ts = datetime.strptime(m.group(1), TIMESTAMP_FMT)
                result.append({
                    'name': f['Name'], 'path': f"{remote_dir}/{f['Name']}",
                    'ts': ts.strftime('%d/%m/%Y %H:%M:%S'),
                    'size_mb': round(f.get('Size', 0) / (1024 * 1024), 1),
                })
        return result

    p = Path(folder) / PDF_ARCHIVE_SUBDIR
    if not p.exists():
        return []
    result = []
    for f in sorted(p.glob(f'{PDF_ARCHIVE_PREFIX}*{PDF_ARCHIVE_EXT}'), reverse=True):
        m = re.search(r'(\d{8}_\d{6})', f.name)
        if m:
            ts = datetime.strptime(m.group(1), TIMESTAMP_FMT)
            result.append({
                'name': f.name, 'path': str(f),
                'ts': ts.strftime('%d/%m/%Y %H:%M:%S'),
                'size_mb': round(f.stat().st_size / (1024 * 1024), 1),
            })
    return result


def list_pdf_archives(folder: str) -> list:
    _check_reachable(folder)
    return _list_pdf_archives(folder)


def _should_run_pdf_archive(folder: str) -> bool:
    archives = _list_pdf_archives(folder)
    if not archives:
        return True
    m = re.search(r'(\d{8}_\d{6})', archives[0]['name'])
    if not m:
        return True
    latest = datetime.strptime(m.group(1), TIMESTAMP_FMT)
    return (datetime.now() - latest).days >= PDF_ARCHIVE_MIN_DAYS


def _prune_pdf_archives(folder: str):
    archives = _list_pdf_archives(folder)  # sorted νεότερο->παλιότερο
    for old in archives[PDF_ARCHIVE_KEEP:]:
        try:
            if _is_rclone(folder):
                subprocess.run([RCLONE_BIN, 'deletefile', old['path']], capture_output=True, timeout=30)
            else:
                Path(old['path']).unlink()
        except Exception:
            pass


def _do_pdf_archive(folder: str, force: bool = False) -> dict:
    if not PDF_STORE_DIR or not os.path.isdir(PDF_STORE_DIR):
        return {'ok': True, 'skipped': 'no pdf_store', 'folder': folder}
    if not force and not _should_run_pdf_archive(folder):
        return {'ok': True, 'skipped': 'not due yet', 'folder': folder}

    # Reachability έλεγχος ΠΡΙΝ φτιαχτεί το zip -- χωρίς αυτό, ένας μη προσβάσιμος
    # προορισμός (π.χ. αποσυνδεδεμένο NAS) έκανε την πλήρη συμπίεση 1.5GB/2740
    # αρχείων (~11s, επιβεβαιωμένο στην πράξη 2026-09-17) πριν καν ανακαλυφθεί ότι
    # δεν υπάρχει πουθενά να παραδοθεί -- σπατάλη χρόνου/CPU/δίσκου για το τίποτα.
    try:
        _check_reachable(folder)
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': folder}

    ts = datetime.now().strftime(TIMESTAMP_FMT)
    name = f'{PDF_ARCHIVE_PREFIX}{ts}{PDF_ARCHIVE_EXT}'
    tmp_dir = tempfile.mkdtemp(prefix='pdf_archive_')
    tmp_zip = os.path.join(tmp_dir, name)
    try:
        with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_STORED) as zf:
            for root, _dirs, files in os.walk(PDF_STORE_DIR):
                for fname in files:
                    full = os.path.join(root, fname)
                    zf.write(full, os.path.relpath(full, PDF_STORE_DIR))

        if _is_rclone(folder):
            dest = f"{folder.rstrip('/')}/{PDF_ARCHIVE_SUBDIR}/{name}"
            r = subprocess.run(
                [RCLONE_BIN, 'copyto', tmp_zip, dest],
                capture_output=True, text=True, timeout=1800
            )
            if r.returncode != 0:
                return {'ok': False, 'error': r.stderr.strip() or r.stdout.strip(), 'folder': folder}
        else:
            dest_dir = Path(folder) / PDF_ARCHIVE_SUBDIR
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = str(dest_dir / name)
            shutil.move(tmp_zip, dest)

        _prune_pdf_archives(folder)
        return {'ok': True, 'path': dest, 'folder': folder}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Timeout (30 λεπτά) στο πλήρες αρχείο pdf_store', 'folder': folder}
    except Exception as e:
        return {'ok': False, 'error': str(e), 'folder': folder}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_pdf_archive_for_all(paths: list, force: bool = False) -> list:
    return [_do_pdf_archive(p, force=force) for p in paths]


def run_pdf_archive_now() -> dict:
    cfg = _load()
    paths = [p for p in cfg.get('paths', []) if p]
    if not paths:
        return {'ok': False, 'error': 'Δεν έχουν οριστεί φάκελοι backup', 'results': []}
    results = run_pdf_archive_for_all(paths, force=True)
    return {'ok': any(r['ok'] for r in results), 'results': results}


def _known_pdf_archive_paths() -> set:
    cfg = _load()
    known = set()
    for folder in [p for p in cfg.get('paths', []) if p]:
        for a in _list_pdf_archives(folder):
            known.add(a['path'])
    return known


PRERESTORE_KEEP = 2  # κρατάει τουλάχιστον 1-2 δίχτυα ασφαλείας, ποτέ ασυγκράτητη συσσώρευση


def _prune_prerestore_folders():
    if not PDF_STORE_DIR:
        return
    parent = Path(PDF_STORE_DIR).parent
    base = Path(PDF_STORE_DIR).name
    siblings = sorted(
        (p for p in parent.glob(f'{base}.prerestore_*') if p.is_dir()),
        key=lambda p: p.name,
    )
    for old in siblings[:-PRERESTORE_KEEP]:
        shutil.rmtree(old, ignore_errors=True)


def restore_pdf_store(path: str) -> dict:
    """Directory-equivalent του restore_backup: rename-aside του τρέχοντος pdf_store
    (φτηνή πράξη ίδιου δίσκου, αντί για ακριβή αντιγραφή 1.2GB σαν δίχτυ ασφαλείας)
    + extract του zip στη θέση του. testzip() = integrity check (πραγματικός CRC
    έλεγχος κάθε αρχείου μέσα στο zip), ίδιο πνεύμα με το PRAGMA integrity_check
    της βάσης.

    Οι παλιοί pdf_store.prerestore_* φάκελοι κρατιούνται σε bounded rotation
    (PRERESTORE_KEEP, ίδιο πνεύμα με το max_keep των DB backups) αντί να μένουν
    επ' αόριστον -- κρατάει πάντα τουλάχιστον ένα δίχτυ ασφαλείας, ποτέ μηδέν."""
    if path not in _known_pdf_archive_paths():
        return {'ok': False, 'error': 'Μη αναγνωρισμένο αρχείο — επιτρέπεται restore μόνο από τα configured backup paths.'}
    if not PDF_STORE_DIR:
        return {'ok': False, 'error': 'pdf_store δεν έχει οριστεί'}

    tmp_download = None
    extract_dir = None
    try:
        if _is_rclone(path):
            fd, tmp_download = tempfile.mkstemp(suffix=PDF_ARCHIVE_EXT)
            os.close(fd)
            r = subprocess.run(
                [RCLONE_BIN, 'copyto', path, tmp_download],
                capture_output=True, text=True, timeout=1800
            )
            if r.returncode != 0:
                return {'ok': False, 'error': r.stderr.strip() or r.stdout.strip()}
            source_path = tmp_download
        else:
            source_path = path

        ts = datetime.now().strftime(TIMESTAMP_FMT)
        extract_dir = f'{PDF_STORE_DIR}.restoring_{ts}'
        try:
            with zipfile.ZipFile(source_path) as zf:
                bad = zf.testzip()
                if bad is not None:
                    return {'ok': False, 'error': f'Κατεστραμμένο αρχείο μέσα στο zip: {bad}'}
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            return {'ok': False, 'error': 'Το αρχείο δεν είναι έγκυρο zip'}

        pdf_store_path = Path(PDF_STORE_DIR)
        if pdf_store_path.exists():
            os.rename(pdf_store_path, f'{PDF_STORE_DIR}.prerestore_{ts}')
        os.rename(extract_dir, PDF_STORE_DIR)
        extract_dir = None

        _prune_prerestore_folders()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    finally:
        if tmp_download:
            try:
                os.unlink(tmp_download)
            except Exception:
                pass
        if extract_dir and os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)


# ── Restore (μόνο DB -- το pdf_store είναι σωρευτικό mirror, δεν χρειάζεται restore
# με την ίδια έννοια: ένα χαμένο PDF θα ξαναβρεθεί εκεί χειροκίνητα αν ποτέ χρειαστεί) ──

def _known_backup_paths() -> set:
    """Defense-in-depth: το restore_backup δέχεται μόνο path που η ίδια η εφαρμογή
    ήδη έδειξε ως δικό της backup (configured paths), όχι αυθαίρετο IPC payload."""
    cfg = _load()
    known = set()
    for folder in [p for p in cfg.get('paths', []) if p]:
        for b in list_backups(folder):
            known.add(b['path'])
    return known


def _validate_sqlite_file(path: str) -> tuple:
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            row = conn.execute('PRAGMA integrity_check').fetchone()
            if not row or row[0] != 'ok':
                return False, 'Το αρχείο απέτυχε στον έλεγχο ακεραιότητας SQLite (integrity_check)'
            return True, ''
        finally:
            conn.close()
    except sqlite3.Error as e:
        return False, f'Μη έγκυρο αρχείο βάσης SQLite: {e}'


def restore_backup(path: str) -> dict:
    if path not in _known_backup_paths():
        return {'ok': False, 'error': 'Μη αναγνωρισμένο backup path — επιτρέπεται restore μόνο από τα configured backup paths.'}

    tmp_path = None
    unpacked_path = None
    try:
        if _is_rclone(path):
            with tempfile.NamedTemporaryFile(suffix=GZ_EXT if path.endswith(GZ_EXT) else EXT, delete=False) as tmp:
                tmp_path = tmp.name
            r = subprocess.run(
                [RCLONE_BIN, 'copyto', path, tmp_path],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode != 0:
                return {'ok': False, 'error': r.stderr.strip() or r.stdout.strip()}
            source_path = tmp_path
        else:
            source_path = path

        if path.endswith(GZ_EXT):
            with tempfile.NamedTemporaryFile(suffix=EXT, delete=False) as tmp:
                unpacked_path = tmp.name
            try:
                with gzip.open(source_path, 'rb') as fin, open(unpacked_path, 'wb') as fout:
                    shutil.copyfileobj(fin, fout)
            except (OSError, EOFError) as e:
                return {'ok': False, 'error': f'Το συμπιεσμένο αντίγραφο είναι κατεστραμμένο: {e}'}
            source_path = unpacked_path

        valid, err = _validate_sqlite_file(source_path)
        if not valid:
            return {'ok': False, 'error': err}

        db_path = Path(DB_PATH)
        if db_path.exists():
            ts = datetime.now().strftime(TIMESTAMP_FMT)
            shutil.copy2(db_path, db_path.parent / f'invoicebook_prerestore_{ts}{EXT}')

        tmp_dest = db_path.parent / f'.{db_path.name}.tmp_restore'
        shutil.copy2(source_path, tmp_dest)
        os.replace(tmp_dest, db_path)

        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    finally:
        for f in (tmp_path, unpacked_path):
            if f:
                try:
                    os.unlink(f)
                except Exception:
                    pass


# ── Χειροκίνητα snapshots πριν από ad-hoc edits (invoicebook.db.bak-*) ────────
# Δημιουργούνται ΕΞΩ από αυτή την εφαρμογή (π.χ. invoices/backend/snapshot_before_edit.py,
# πριν από ένα πρόχειρο SQL edit) -- τελείως ξεχωριστό από το τακτικό backup παραπάνω.
# Αυτό εδώ είναι μόνο ΟΡΑΤΟΤΗΤΑ + χειροκίνητος καθαρισμός μέσα από το ίδιο το UI, ώστε να
# μην εξαρτάται κανείς από το να θυμηθεί να τρέξει το script/να τα δει με το χέρι --
# ανεξάρτητο δίχτυ ασφαλείας αν κάποιο edit έγινε χωρίς το snapshot tool (π.χ. raw cp).
MANUAL_SNAPSHOT_KEEP = 30       # ίδιο default με το snapshot_before_edit.py's KEEP
# Πρέπει να είναι > KEEP, όχι <. Το "Καθάρισε παλιά" κλαδεύει μόνο ΩΣ το KEEP, ποτέ
# από κάτω -- αν το warn threshold ήταν ≤ KEEP, μετά την πρώτη φορά που φτάνει εκεί
# η προειδοποίηση θα έμενε ΜΟΝΙΜΗ (το steady-state μετά το καθάρισμα είναι ακριβώς
# KEEP αρχεία, άρα ποτέ δεν θα έπεφτε ξανά κάτω από το threshold). Πάνω από KEEP
# σημαίνει ότι όντως συσσωρεύτηκαν παραπάνω απ' ό,τι θα έπρεπε (π.χ. edit χωρίς το
# snapshot tool) -- ακριβώς η περίπτωση που το καθάρισμα λύνει και η προειδοποίηση
# πρέπει να εξαφανιστεί μετά.
MANUAL_SNAPSHOT_WARN_AT = MANUAL_SNAPSHOT_KEEP + 5


def _manual_snapshot_dir() -> Path:
    return Path(DB_PATH).parent


def _list_manual_snapshot_files() -> list:
    d = _manual_snapshot_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob('invoicebook.db.bak-*'), key=lambda p: p.stat().st_mtime)


def list_manual_snapshots() -> dict:
    files = _list_manual_snapshot_files()
    total_size = sum(f.stat().st_size for f in files)
    return {
        'count': len(files),
        'size_mb': round(total_size / (1024 * 1024), 1),
        'oldest': files[0].name if files else None,
        'newest': files[-1].name if files else None,
        'warn': len(files) >= MANUAL_SNAPSHOT_WARN_AT,
        'keep': MANUAL_SNAPSHOT_KEEP,
    }


def prune_manual_snapshots() -> dict:
    files = _list_manual_snapshot_files()
    to_delete = files[:-MANUAL_SNAPSHOT_KEEP] if len(files) > MANUAL_SNAPSHOT_KEEP else []
    deleted = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    return {'ok': True, 'deleted': deleted, **list_manual_snapshots()}


def run_all_backups(reason: str = None) -> dict:
    cfg = _load()
    paths = [p for p in cfg.get('paths', []) if p]
    max_keep = cfg.get('max_keep', 20)

    if not paths:
        return {'ok': False, 'error': 'Δεν έχουν οριστεί φάκελοι backup', 'results': []}

    current = _current_state()
    dest_state = cfg.get('dest_state', {})

    run_start = time.monotonic()
    results = []
    any_ok = False
    for p in paths:
        dest_start = time.monotonic()
        if _unchanged_since_last_ok(p, dest_state, current):
            results.append({'folder': p, 'skipped': 'no changes since last backup', 'elapsed_sec': round(time.monotonic() - dest_start, 1)})
            any_ok = True
            continue

        r_db = do_backup(p, max_keep, reason)
        r_pdf = _backup_pdf_store(p)
        r_pdf_archive = _do_pdf_archive(p)  # staleness-gated, no-op τις περισσότερες φορές
        results.append({
            'folder': p, 'db': r_db, 'pdf_store': r_pdf, 'pdf_archive': r_pdf_archive,
            'elapsed_sec': round(time.monotonic() - dest_start, 1),
        })
        # ok για σκοπούς του content-fingerprint gate: αυστηρότερο από το any_ok παρακάτω --
        # ένα πραγματικό σφάλμα στο mirror (όχι σκόπιμο skip, π.χ. Drive) δεν πρέπει να
        # "κλειδώσει" σαν επιτυχία, αλλιώς ένας μόνιμα σπασμένος προορισμός θα σταματούσε
        # να ξαναδοκιμάζεται μόλις τύχαινε μία φορά να μη έχει αλλάξει τίποτα.
        dest_state[p] = {**current, 'ok': bool(r_db.get('ok')) and (bool(r_pdf.get('ok')) or r_pdf.get('skipped') is not None)}
        if r_db['ok'] or r_pdf['ok']:
            any_ok = True
    total_elapsed_sec = round(time.monotonic() - run_start, 1)

    cfg['dest_state'] = dest_state
    ts = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    cfg['last_backup'] = ts
    cfg['last_status'] = 'ok' if any_ok else 'error'
    cfg['last_duration_sec'] = total_elapsed_sec
    _save(cfg)

    return {'ok': any_ok, 'results': results, 'last_backup': ts, 'total_elapsed_sec': total_elapsed_sec}
