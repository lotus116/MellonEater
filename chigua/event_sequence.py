"""Build reader timeline rows from distinct, source-anchored actions."""
import re
from datetime import datetime, timedelta

from .core import ROOT, STR, TIMED_ARC_STEP, TIMED_READER_SCHEMA, schema_obj

RULES = (ROOT/'skills/chigua-analysis/references/event-sequence.md').read_text()
KINDS = ('原始言行', '公开披露', '回击', '事后解释', '其他')
TIME_ORIGINS = ('消息时间', '图内时间', '原文所述时间', '未知')

# Display time expressions only. The excerpt explaining a date or order
# belongs in the source, not in the time label.
TIME_WORDS = re.compile(
    r'(?:\d{4}年)?\d{1,2}月\d{1,2}[日号](?:早上|上午|中午|下午|傍晚|晚间|晚上|晚|凌晨)?'
    r'(?:\s*\d{1,2}[:：]\d{2})?'
    r'|(?:昨天|昨日|前天|今天|当天|当晚|隔天|次日|次晚)(?:\s*\d{1,2}[:：]\d{2})?'
    r'|\d{1,2}[:：]\d{2}'
    r'|[0-9一二两三四五六七八九十几数]+天(?:前|后)'
    r'|贴完|转发后|发出后|看到后|会后|赛前|赛后|比赛期间|准备期间'
)
EMBEDDED_TEXT = re.compile(r'^\s*[【\[（(][^】\]）)\n]{0,70}(?:转发|补贴|旧对话|摘录|转述|截图)[^】\]）)\n]{0,70}[】\]）)]')
RELATIVE_EXPRESSION = re.compile(r'^(?:贴完|转发后|发出后|看到后|会后|赛前|赛后)$')
DATE_WORDS = re.compile(r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]')


def schema(anchor):
    time_origins = {'type':'string','enum':list(TIME_ORIGINS)}
    item = schema_obj({
        'position': STR,
        'source_check':schema_obj({**anchor['properties'],'time_origin':time_origins}),
        **{key:value for key,value in TIMED_ARC_STEP['properties'].items() if key != 'event_time'},
    })
    return schema_obj({kind:{'type':'array','items':item} for kind in KINDS})


def reader_schema(actions):
    story = TIMED_READER_SCHEMA['properties']['story']['properties']
    return schema_obj({
        **TIMED_READER_SCHEMA['properties'],
        'story':schema_obj({**{key:value for key,value in story.items() if key != 'arc'}, 'actions':actions}),
    })


def flatten(actions):
    rows = [{**row, 'action_kind':kind} for kind in KINDS for row in actions[kind]]
    if any(not re.fullmatch(r'[1-9][0-9]?', row['position']) for row in rows):
        raise ValueError('时间线节点 position 必须是正整数字符串。')
    positions = [int(row['position']) for row in rows]
    if len(set(positions)) != len(rows):
        raise ValueError('时间线节点 position 重复。')
    return sorted(rows, key=lambda row: int(row['position']))


def regroup(arc):
    actions = {kind:[] for kind in KINDS}
    for row in arc:
        item = {key:value for key,value in row.items() if key not in {'action_kind','event_time'}}
        actions[row['action_kind']].append(item)
    return actions


def source_content(anchor, messages, images):
    row = messages.get(anchor['source_id'], {})
    image = images.get(row.get('image_observation_ref'), {})
    content = row.get('text', '') if anchor['from'] == 'text' else image.get('visible_text', '')
    return row, image, content


def source_day(quote, row):
    match = DATE_WORDS.match(quote)
    if not match:
        return None
    year, month, day = match.groups()
    stamp = row.get('message_time')
    try:
        if not year and not stamp:
            return None
        reference = datetime.fromisoformat(stamp).date() if stamp else None
        day = datetime(int(year) if year else reference.year, int(month), int(day)).date()
        # An ambiguous year is common when a conversation spans New Year.
        return day if year or abs(day-reference) <= timedelta(days=180) else None
    except ValueError:
        return None


def event_time(step, messages, images):
    """Return a checked display time and an optional day for ordering."""
    check = step['source_check']
    anchor = check['anchor']
    row, image, content = source_content(anchor, messages, images)
    origin = check['time_origin']
    quote = check['time_quote'].strip()
    if origin == '未知':
        relative = RELATIVE_EXPRESSION.fullmatch(quote) and quote in anchor['quote']
        return '', None, (not quote or bool(relative)) and step['order_basis'] != '时间戳可确认'
    if not quote:
        return '', None, False

    if origin == '消息时间':
        stamp = row.get('message_time')
        if (anchor['from'] != 'text' or quote != stamp
                or check['mode'] == '后来回述'
                or (EMBEDDED_TEXT.match(content) and check['mode'] != '转述行为本身')
                or (row.get('image_observation_ref') and check['mode'] != '转述行为本身')
                or (check['mode'] == '转述行为本身' and step['action_kind'] != '公开披露')
                or (stamp == row.get('forwarded_at') and step['action_kind'] != '公开披露')):
            return '', None, False
        try:
            date = datetime.fromisoformat(stamp)
        except ValueError:
            return '', None, False
        return f'{date.month}月{date.day}日 {date:%H:%M}', date.date(), True

    if not TIME_WORDS.fullmatch(quote):
        return '', None, False
    if origin == '原文所述时间':
        # Exported excerpts can put their inner date in a header just before
        # the utterance. This is text from the material, not wrapper metadata.
        prefix = content.partition(anchor['quote'])[0]
        header = prefix[-80:] if DATE_WORDS.match(quote) and content.count(anchor['quote']) == 1 else ''
        if anchor['from'] != 'text' or (quote not in anchor['quote'] and quote not in header):
            return '', None, False
        basis = "据回述" if check["mode"] == "后来回述" else "原文标注"
        label = f'{quote}（{basis}）'
        return ('' if RELATIVE_EXPRESSION.fullmatch(quote) else label), source_day(quote,row), True

    if anchor['from'] != 'image' or check['mode'] != '当时记录':
        return '', None, False
    # The matching chat clock must be the closest preceding chat time
    # within the transcript, beyond the device UI. Never use its wrapper.
    before, found, _ = content.partition(anchor['quote'])
    if not found or content.count(anchor['quote']) != 1:
        return '', None, False
    candidates = [line.strip() for line in before.strip().splitlines()[1:]
                  if TIME_WORDS.fullmatch(line.strip())]
    if not candidates or candidates[-1] != quote or quote not in image['visible_time']:
        return '', None, False
    return f'{quote}（图内）', None, True


def normalize(candidate, pack):
    """Attach event clocks to the internal draft and return local findings."""
    messages = {row['id']:row for row in pack['messages']}
    images = {obs['source_id']:obs for obs in pack['image_observations']}
    limits = []
    dated = []
    bases = {}
    unsupported = []
    for index, step in enumerate(candidate['reader']['story']['arc'], 1):
        check = step['source_check']
        anchor = check['anchor']
        _, _, content = source_content(anchor,messages,images)
        grounded = (all(check[key].strip() for key in ('actor','scene','basis'))
                    and anchor['source_id'] in step['source_ids']
                    and bool(anchor['quote'].strip()) and anchor['quote'] in content)
        label, absolute, checked = event_time(step,messages,images) if grounded else ('',None,False)
        step['event_time'] = label
        if not checked:
            fallback = '当事人回述' if grounded and check['mode'] == '后来回述' else '先后未确认'
            unsupported.append((index-1, fallback))
            limits.append(f'「{step["stage"]}」的发生时间或原文依据未能核对。')
        if checked and check['mode'] == '后来回述' and step['order_basis'] != '先后未确认':
            bases[index-1] = '当事人回述'
        elif checked and check['time_origin'] == '原文所述时间' and step['order_basis'] == '时间戳可确认':
            bases[index-1] = '相对顺序可确认'
        if absolute is not None:
            dated.append((index-1,absolute))
    return limits, unsupported, bases, dated


def order_dated(arc, dated):
    """Sort comparable adjacent days without passing any undated action."""
    changed = False
    start = 0
    days = dict(dated)
    for end in range(len(arc)+1):
        if end in days:
            continue
        indices = sorted(range(start,end), key=days.__getitem__)
        if indices != list(range(start,end)):
            arc[start:end] = [arc[index] for index in indices]
            changed = True
        start = end+1
    return changed
