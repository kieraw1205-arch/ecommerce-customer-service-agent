"""Unlabeled input schema only; the private MySQL execution worker is excluded."""
def validate_inputs(document):
    if set(document) != {'version','cases'} or document['version'] != 'holdout-v1':
        raise ValueError('invalid input schema')
    seen=set()
    for case in document['cases']:
        if set(case) != {'id','actor','turns'} or case['id'] in seen or case['actor'] not in {'alice','bob'}:
            raise ValueError('input must not contain labels')
        seen.add(case['id'])
        if not 1 <= len(case['turns']) <= 4: raise ValueError('turn bound')
        for index,turn in enumerate(case['turns']):
            if not set(turn) <= {'text','reuse_previous_message_id'} or not isinstance(turn.get('text'),str):
                raise ValueError('invalid turn')
            if turn.get('reuse_previous_message_id') and index==0: raise ValueError('no previous message')
    return document['cases']
