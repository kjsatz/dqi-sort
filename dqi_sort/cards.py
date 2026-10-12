"""Stage 2: presentation cards, written by Claude Haiku subagents in Claude Code.

    python -m dqi_sort.cards prepare DATA_DIR [--ids FILE] [--batch-size 100]
    python -m dqi_sort.cards check BATCH.out.json        (a subagent runs this on its own output)
    python -m dqi_sort.cards merge DATA_DIR

prepare writes DATA_DIR/work/cards/: prompt.md (prompts/card_spec.md with this year's categories and
other APS units filled in) and batch_NNN.json, one per batch of talks that have no card yet (or the
talks listed in --ids, one talk ID per line). Talks with no abstract are skipped and listed: some
invited talks arrive with only the speaker's name, and a card made from that would be a placeholder. Each talk carries talk_id, type, title, body,
submitter_notes and affiliation; speaker names are never included.

A Haiku subagent then reads prompt.md and one batch file and writes batch_NNN.out.json next to it.

merge checks every batch_NNN.out.json against its batch and adds the valid cards to DATA_DIR/cards.jsonl
(sorted by talk ID; a talk's existing card is replaced). Batches with problems are listed and skipped,
so they can be rerun on their own.
"""
import argparse, glob, json, os, sys
import yaml

PROMPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'prompts', 'card_spec.md')
KEYS = ['talk_id', 'platform', 'problem', 'approach', 'key_claim', 'keywords', 'best_category',
        'runner_up_category', 'session_pitch', 'affiliation', 'multi_part', 'constraints',
        'leadership_review', 'other_unit', 'malformed']
APPROACHES = {'experiment', 'theory', 'simulation/modeling', 'fabrication/materials characterization', 'methods/tooling'}


def id_key(i):
    return (len(i), i)


def read_jsonl(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}


def load_config(data_dir):
    with open(os.path.join(data_dir, 'config.yaml'), encoding='utf-8') as f:
        return yaml.safe_load(f)


def work_dir(data_dir):
    return os.path.join(data_dir, 'work', 'cards')


# ---------- prepare ----------
def prompt_text(cfg):
    cats = '\n'.join(f'- {k}: {v}' for k, v in (cfg.get('dqi_categories') or {}).items())
    units = '\n'.join(f'- {k}: {v}' for k, v in (cfg.get('other_units') or {}).items())
    with open(PROMPT, encoding='utf-8') as f:
        return f.read().replace('{CATEGORIES}', cats).replace('{UNITS}', units)


def prepare(data_dir, ids_file, batch_size):
    import csv
    cfg = load_config(data_dir)
    abstracts = read_jsonl(os.path.join(data_dir, 'abstracts.jsonl'))
    with open(os.path.join(data_dir, 'talks.csv'), encoding='utf-8', newline='') as f:
        talks = {r['talk_id']: r for r in csv.DictReader(f)}
    if ids_file:
        with open(ids_file, encoding='utf-8') as f:
            ids = [l.strip() for l in f if l.strip()]
        missing = [i for i in ids if i not in talks]
        if missing:
            sys.exit(f'unknown talk IDs: {missing[:10]}')
    else:
        done = read_jsonl(os.path.join(data_dir, 'cards.jsonl'))
        ids = [i for i in talks if i not in done and talks[i]['status'] == 'active']
    no_text = [i for i in ids if not abstracts[i]['body'].strip()]
    if no_text:
        print(f'skipping {len(no_text)} talks with no abstract (a card needs content; add the text first): '
              + ' '.join(sorted(no_text, key=id_key)[:12]) + (' ...' if len(no_text) > 12 else ''))
    ids = sorted((i for i in ids if i not in no_text), key=id_key)
    out = work_dir(data_dir)
    os.makedirs(out, exist_ok=True)
    pending = glob.glob(os.path.join(out, 'batch_*.out.json'))
    if pending:
        sys.exit(f'{len(pending)} batch outputs in {out} are not cleared; run merge first, then delete them')
    for old in glob.glob(os.path.join(out, 'batch_[0-9][0-9][0-9].json')):
        os.remove(old)
    with open(os.path.join(out, 'prompt.md'), 'w', encoding='utf-8') as f:
        f.write(prompt_text(cfg))
    n = 0
    for k in range(0, len(ids), batch_size):
        batch = [{'talk_id': i, 'type': talks[i]['type'], 'title': abstracts[i]['title'],
                  'body': abstracts[i]['body'], 'submitter_notes': abstracts[i]['submitter_notes'],
                  'affiliation': talks[i]['affiliation']} for i in ids[k:k + batch_size]]
        with open(os.path.join(out, f'batch_{n:03d}.json'), 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=1)
        n += 1
    print(f'{len(ids)} talks in {n} batches of up to {batch_size} in {out}')


# ---------- check ----------
def problems(card, cfg):
    """Return a list of problems with one card (empty if it is valid)."""
    p = []
    if list(card) != KEYS:
        extra, missing = set(card) - set(KEYS), [k for k in KEYS if k not in card]
        if extra or missing:
            return [f'keys: missing {missing}, unexpected {sorted(extra)}']
    for k in ('platform', 'problem', 'key_claim', 'session_pitch', 'affiliation'):
        if not isinstance(card[k], str):
            p.append(f'{k} must be a string')
    if card['approach'] not in APPROACHES:
        p.append(f"approach {card['approach']!r} not one of {sorted(APPROACHES)}")
    kw = card['keywords']
    if not (isinstance(kw, list) and 3 <= len(kw) <= 6 and all(isinstance(x, str) for x in kw)):
        p.append('keywords must be a list of 3-6 strings')
    cats = cfg.get('dqi_categories') or {}
    if cats and card['best_category'] not in cats:
        p.append(f"best_category {card['best_category']!r} is not a DQI category code")
    if card['runner_up_category'] is not None and cats and card['runner_up_category'] not in cats:
        p.append(f"runner_up_category {card['runner_up_category']!r} is not a DQI category code")
    mp = card['multi_part']
    if mp is not None and not (isinstance(mp, dict) and {'part', 'of', 'partner_hint'} <= set(mp)):
        p.append('multi_part must be null or {part, of, partner_hint}')
    lr = card['leadership_review']
    if lr is not None and not (isinstance(lr, dict) and {'flag', 'reason'} <= set(lr)):
        p.append('leadership_review must be null or {flag, reason}')
    ou = card['other_unit']
    units = cfg.get('other_units') or {}
    if ou is not None:
        if not (isinstance(ou, dict) and {'unit', 'strength', 'reason'} <= set(ou)):
            p.append('other_unit must be null or {unit, strength, reason}')
        elif units and ou['unit'] not in units:
            p.append(f"other_unit.unit {ou['unit']!r} is not in the unit list")
        elif ou['strength'] not in ('could fit', 'belongs there'):
            p.append("other_unit.strength must be 'could fit' or 'belongs there'")
    mf = card['malformed']
    if mf is not None and not (isinstance(mf, dict) and {'issue', 'suggested_fix'} <= set(mf)):
        p.append('malformed must be null or {issue, suggested_fix}')
    if card['constraints'] is not None and not isinstance(card['constraints'], str):
        p.append('constraints must be null or a string')
    return p


def check_batch(out_path, cfg):
    """Return (cards, errors) for one batch output, checked against its batch file."""
    in_path = out_path.replace('.out.json', '.json')
    try:
        with open(out_path, encoding='utf-8') as f:
            cards = json.load(f)
    except (OSError, ValueError) as e:
        return [], [f'cannot read {out_path}: {e}']
    with open(in_path, encoding='utf-8') as f:
        talks = json.load(f)
    errs = []
    if not isinstance(cards, list):
        return [], ['output must be a JSON array']
    want = [t['talk_id'] for t in talks]
    got = [c.get('talk_id') if isinstance(c, dict) else None for c in cards]
    if got != want:
        errs.append(f'talk_ids differ from the batch: {len(got)} cards for {len(want)} talks; '
                    f'missing {[i for i in want if i not in got][:10]}, unexpected {[i for i in got if i not in want][:10]}')
    aff = {t['talk_id']: t['affiliation'] for t in talks}
    for c in cards:
        if not isinstance(c, dict):
            errs.append('every card must be a JSON object')
            continue
        for e in problems(c, cfg):
            errs.append(f"{c.get('talk_id')}: {e}")
        if c.get('talk_id') in aff and c.get('affiliation') != aff[c['talk_id']]:
            errs.append(f"{c['talk_id']}: affiliation must be copied exactly from the input")
    return cards, errs


def find_data_dir(path):
    d = os.path.dirname(os.path.abspath(path))
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, 'config.yaml')):
            return d
        d = os.path.dirname(d)
    sys.exit('no config.yaml above ' + path)


def check(out_path):
    cfg = load_config(find_data_dir(out_path))
    cards, errs = check_batch(out_path, cfg)
    for e in errs:
        print('ERROR', e)
    print(f'OK: {len(cards)} cards' if not errs else f'{len(errs)} errors')
    sys.exit(1 if errs else 0)


# ---------- merge ----------
def merge(data_dir):
    cfg = load_config(data_dir)
    path = os.path.join(data_dir, 'cards.jsonl')
    cards = read_jsonl(path)
    added, bad = 0, []
    for out in sorted(glob.glob(os.path.join(work_dir(data_dir), 'batch_*.out.json'))):
        got, errs = check_batch(out, cfg)
        if errs:
            bad.append((os.path.basename(out), errs))
            continue
        for c in got:
            cards[c['talk_id']] = c
            added += 1
    with open(path, 'w', encoding='utf-8') as f:
        for i in sorted(cards, key=id_key):
            f.write(json.dumps(cards[i], ensure_ascii=False) + '\n')
    print(f'merged {added} cards; cards.jsonl now has {len(cards)}')
    if not bad:
        print('all batches merged; their outputs in work/cards/ can now be deleted')
    for name, errs in bad:
        print(f'SKIPPED {name}: {len(errs)} problems, e.g. {errs[0]}')
    flags = {k: sum(c[k] is not None for c in cards.values()) for k in ('leadership_review', 'other_unit', 'malformed', 'multi_part')}
    print('flags across all cards:', flags)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare'); p.add_argument('data_dir'); p.add_argument('--ids'); p.add_argument('--batch-size', type=int, default=100)
    c = sub.add_parser('check'); c.add_argument('out_json')
    m = sub.add_parser('merge'); m.add_argument('data_dir')
    a = ap.parse_args()
    if a.cmd == 'prepare':
        prepare(a.data_dir, a.ids, a.batch_size)
    elif a.cmd == 'check':
        check(a.out_json)
    else:
        merge(a.data_dir)


if __name__ == '__main__':
    main()
