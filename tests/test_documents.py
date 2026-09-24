from devflow import documents


def test_requirement_wish_and_source():
    r = documents.requirement('X (Jira: описание; пожелание)')
    assert r == {'text': 'X', 'source': 'Jira: описание; пожелание', 'wish': True}


def test_requirement_plain_and_no_source():
    assert documents.requirement('Y (ТЗ)') == {'text': 'Y', 'source': 'ТЗ', 'wish': False}
    assert documents.requirement('Z') == {'text': 'Z', 'source': '', 'wish': False}


def test_section_items_joins_wrapped_lines():
    body = '# T\n\n## Requirements\n- первое\n  продолжение (ТЗ)\n- второе (Jira: описание)\n\n## Next\n- чужое\n'
    assert documents.section_items(body, 'Requirements') == [
        'первое продолжение (ТЗ)', 'второе (Jira: описание)']


def test_section_items_missing():
    assert documents.section_items('# T\n\n## Problem\n- x\n', 'Requirements') == []
