from dqi_sort import sheets as Sh


def test_bands_alternate_by_session_and_skip_notes():
    reqs = Sh.band_requests(7, ['A', 'A', 'B', 'C', 'C'], 4, bold_rows=[1], skip_cols=[3])
    shaded = [(r['repeatCell']['range']['startRowIndex'], r['repeatCell']['range']['endRowIndex'],
               r['repeatCell']['range']['endColumnIndex']) for r in reqs if 'backgroundColor' in r['repeatCell']['cell']['userEnteredFormat']]
    h = Sh.HEADER_ROW
    assert shaded == [(h, h + 2, 3), (h + 3, h + 5, 3)]        # sessions A and C shaded, B plain; notes column left alone
    assert any('bold' in r['repeatCell']['fields'] for r in reqs)


def test_area_book_rows_and_fill_formula():
    talks = {'1': {'title': 'T1', 'speaker': 'P', 'institution': 'U', 'affiliation': 'U', 'minutes': '36', 'type': 'invited'},
             '2': {'title': 'T2', 'speaker': 'Q', 'institution': 'V', 'affiliation': 'V', 'minutes': '12', 'type': 'oral'}}
    sess = [{'session_id': 'X01', 'title': 'Topic', 'kind': 'mini-symposium', 'minutes': '108', 'size': '', 'notes': '',
             'area': 'X', 'talks': ['1', '2'], 'used': 48}]
    b = Sh.area_book('X', 'Area X', 1, 'Generated from git abc1234', sess, talks, {}, {}, [])
    names = [t[0] for t in b.tabs]
    assert names == ['Session summary', 'Sessions']
    summary_rows, session_rows = b.tabs[0][2], b.tabs[1][2]
    assert summary_rows[0][4].startswith('=SUMIFS(Sessions!$G$3:$G$4')
    assert [r[2] for r in session_rows] == ['1', '2'] and session_rows[0][8] is False


def test_assignments_tab_first_and_only_two_columns_open():
    from dqi_sort import sheets as SH
    b = SH.shared_book('Y', 'stamp', [], {}, {}, {}, [], [], [['QEC', 'error correction', '=HYPERLINK("u", "QEC round 1")', 1, 15, 160, 'A. B.', 'done', 't']])
    name, header, rows, fmt = b.tabs[0]
    assert name == SH.ASSIGN_TAB and header[6:8] == ['Responsible', 'Status']
    prot = [r['addProtectedRange']['protectedRange'] for r in fmt(7, len(rows)) if 'addProtectedRange' in r]
    assert [(u['startColumnIndex'], u['endRowIndex'] - u['startRowIndex']) for u in prot[0]['unprotectedRanges']] == [(6, 1), (7, 1)]
    assert all(any('addProtectedRange' in r for r in f(9, 0)) for _, _, _, f in b.tabs[1:])    # the other tabs are locked
