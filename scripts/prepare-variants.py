"""Create synthetic smoke-test variants only; never fabricate real-case gold labels."""
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chigua.core import DATA, now, normalize_messages, fingerprint, write_json
from chigua.pipeline import save_case

obj=json.loads((DATA/'samples/demo.json').read_text())
base={'title':obj['title'],'source_note':obj['source_note'],'question':'是否有充分证据认定乙超预算、甲拒绝报销？请还原事实并评价双方表达。','identity':'旁观者','messages':normalize_messages(obj['messages'])}
variants=[]
def add(name,mutate,expectation):
    c=copy.deepcopy(base);mutate(c);c['id']='smoke'+name;c['created_at']=now();c['title']='合成测试 / '+name;c['input_hash']=fingerprint(c['messages']);save_case(c)
    variants.append({'case_id':c['id'],'variant':name,'expected_behavior':expectation,'type':'synthetic','human_score':None})
add('original',lambda c:None,'保留对实际金额的判断；不能把同源传闻视为双重证实。材料中没有直接拒绝报销的表达。')
add('identity',lambda c:c.update(identity='我是甲'), '核心事实依据保持；对甲的建议可以变化。')
add('added',lambda c:c['messages'].append({'id':'D009','speaker':'乙','text':'补充：我确认之前说错了，实际付款是 900 元，也没有事先征得同意。','timestamp':None,'source_name':'合成新增材料','source_kind':'合成陈述','source_root':None,'parent_id':None,'forwarded_at':None,'unit':'消息','image':None,'ocr_lines':[],'uncertainty':''}), '撤回“乙只声称支付560”的最新状态；指出其新陈述与旧陈述冲突，并结合600上限作有条件评价。不自动证明甲故意拒付。')
add('removed',lambda c:c.update(messages=[m for m in c['messages'] if m['id']!='D001']), '缺少600预算原始约定，不能仍无依据地认定违反600上限；其余可判断部分仍保留。')
write_json(DATA/'private/smoke-manifest.json',{'created_at':now(),'note':'仅用于MVP行为检查；不是正式研究数据。预期标签不传给模型。','variants':variants})
print(json.dumps(variants,ensure_ascii=False,indent=2))
