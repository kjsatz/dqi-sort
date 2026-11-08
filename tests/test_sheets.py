from dqi_sort import sheets as Sh


def test_bands_alternate_by_session_and_skip_notes():
    reqs = Sh.band_requests(7, ['A', 'A', 'B', 'C', 'C'], 4, bold_rows=[1], skip_cols=[3])
    shaded = [(r['repeatCell']['range']['startRowIndex'], r['repeatCell']['range']['endRowIndex'],
               r['repeatCell']['range']['endColumnIndex']) for r in reqs if 'backgroundColor' in r['repeatCell']['cell']['userEnteredFormat']]
    h = Sh.HEADER_ROW
    assert shaded == [(h, h + 2, 3), (h + 3, h + 5, 3)]        # sessions A and C shaded, B plain; notes column left alone
    assert any('bold' in r['repeatCell']['fields'] for r in reqs)


def test_area_book_rows_and_fill_formula():
    talks = {'1': {'title': 'T1', 'speaker': 'P', 'institution': 'U', 'affiliation': 'U', 'minutes': '36', 'type': 'invited', 'abstract': 'An abstract.'},
             '2': {'title': 'T2', 'speaker': 'Q', 'institution': 'V', 'affiliation': 'V', 'minutes': '12', 'type': 'oral'}}
    sess = [{'session_id': 'X01', 'title': 'Topic', 'kind': 'mini-symposium', 'minutes': '108', 'size': '', 'notes': '',
             'area': 'X', 'talks': ['1', '2'], 'used': 48}]
    b = Sh.area_book('X', 'Area X', 1, 'Generated from git abc1234', sess, talks, {}, {}, [], {'1': 0.912})
    names = [t[0] for t in b.tabs]
    assert names == ['Session summary', 'Sessions']
    summary_rows, session_rows = b.tabs[0][2], b.tabs[1][2]
    assert summary_rows[0][4].startswith('=SUMIFS(Sessions!$H$3:$H$4') and '$L$3:$L$4' in summary_rows[0][4]   # minutes in H, checkbox in L
    assert [r[3] for r in session_rows] == ['1', '2'] and session_rows[0][11] is False           # checkbox in L
    assert session_rows[0][10] == 'An abstract.'                                                 # abstract in K
    assert [r[8] for r in session_rows] == [0.912, '']                                          # fit in I; none without an embedding
    fmt = b.tabs[1][3](5, 2)
    grad = [r['addConditionalFormatRule']['rule'] for r in fmt if 'addConditionalFormatRule' in r]
    assert len(grad) == 1 and grad[0]['ranges'][0]['startColumnIndex'] == 8
    assert [grad[0]['gradientRule'][k]['value'] for k in ('minpoint', 'midpoint', 'maxpoint')] == ['0.73', '0.86', '0.99']
    assert session_rows[1][1].startswith("=IFERROR(VLOOKUP(A4,'Session summary'")     # the session title, following edits
    assert b.top['Session summary'][Sh.COMMENTS_COL - 2] == Sh.COMMENTS_LABEL           # the label in F1, the box in G1
    assert 'Sessions' not in b.top


def test_assignments_tab_first_and_only_two_columns_open():
    from dqi_sort import sheets as SH
    b = SH.shared_book('Y', 'stamp', [], {}, {}, {}, [], [], [['QEC', 'error correction', '=HYPERLINK("u", "QEC round 1")', 1, 15, 160, 'A. B.', 'done', 't']])
    name, header, rows, fmt = b.tabs[0]
    assert name == SH.ASSIGN_TAB and header[6:8] == ['Responsible', 'Status']
    prot = [r['addProtectedRange']['protectedRange'] for r in fmt(7, len(rows)) if 'addProtectedRange' in r]
    assert [(u['startColumnIndex'], u['endRowIndex'] - u['startRowIndex']) for u in prot[0]['unprotectedRanges']] == [(6, 1), (7, 1)]
    assert all(any('addProtectedRange' in r for r in f(9, 0)) for _, _, _, f in b.tabs[1:])    # the other tabs are locked


def test_held_back_needs_a_status_not_just_a_name():
    last = {'A': {'round': '2'}, 'B': {'round': '2'}, 'C': {'round': '1'}}
    status = {'A': ('Ann', ''), 'B': ('Bob', 'in progress'), 'C': ('Cy', 'Done')}
    assert Sh.held_back(['A', 'B', 'C'], last, {('C', '1')}, status) == ['B']    # A not started; C read back


def test_plain_abstract_text():
    assert Sh.plain('<p>We show &mu;s <em>coherence</em>.</p><p>Second.</p>') == 'We show μs coherence.\nSecond.'


class FakeDrive:
    """Just enough of the Drive v3 permissions API for the sharing helpers."""
    def __init__(self, perms):
        self.perms, self.created = perms, []

    def permissions(self):
        return self

    def list(self, fileId, fields):
        return _Run({'permissions': self.perms.get(fileId, [])})

    def create(self, fileId, body, fields, **kw):
        self.created.append((fileId, body, kw))
        return _Run({'id': 'p'})


class _Run:
    def __init__(self, value):
        self.value = value

    def execute(self, num_retries=0):
        return self.value


def test_new_round_keeps_previous_access_and_adds_link_sharing():
    from dqi_sort import gsheets
    drive = FakeDrive({'old': [{'type': 'user', 'role': 'owner', 'emailAddress': 'lead@example.org'},
                               {'type': 'user', 'role': 'writer', 'emailAddress': 'reviewer@example.org'},
                               {'type': 'domain', 'role': 'commenter', 'domain': 'example.org', 'allowFileDiscovery': False}]})
    gsheets.share(drive, 'new', gsheets.new_sheet_access(drive, 'old', 'reader'))
    bodies = [(b['type'], b['role'], b.get('emailAddress') or b.get('domain')) for _, b, _ in drive.created]
    assert bodies == [('user', 'writer', 'reviewer@example.org'), ('domain', 'commenter', 'example.org'), ('anyone', 'reader', None)]
    assert drive.created[0][2] == {'sendNotificationEmail': False}               # reviewers are not emailed
    assert all(f == 'new' for f, _, _ in drive.created)


def test_link_sharing_only_when_set_and_not_doubled():
    from dqi_sort import gsheets
    drive = FakeDrive({'old': [{'type': 'anyone', 'role': 'commenter', 'allowFileDiscovery': False}]})
    assert gsheets.new_sheet_access(drive, None, None) == []
    assert gsheets.new_sheet_access(drive, 'old', 'reader') == [{'type': 'anyone', 'role': 'commenter', 'allowFileDiscovery': False}]
    import pytest
    with pytest.raises(ValueError):
        gsheets.new_sheet_access(drive, None, 'owner')


def test_protected_ranges_are_owner_only():
    b = Sh.shared_book('Y', 'stamp', [], {}, {}, {}, [], [], [['QEC', 'q', 'link', 1, 1, 1, '', '', 't']], owner='lead@example.com')
    assert b.owner == 'lead@example.com'
    reqs = Sh.owner_only(b.tabs[0][3](7, 1), b.owner)
    prot = [r['addProtectedRange']['protectedRange'] for r in reqs if 'addProtectedRange' in r]
    assert prot and all(p['editors'] == {'users': ['lead@example.com']} for p in prot)
    assert all('editors' not in r.get('addProtectedRange', {}).get('protectedRange', {}) for r in Sh.owner_only(b.tabs[0][3](7, 1), None))
