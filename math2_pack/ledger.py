"""Hash-chained append-only learning events, atomic offline imports and replay."""
from __future__ import annotations
from pathlib import Path
import copy
import json
from .util import canonical,sha,atomic_write,atomic_bytes,write_json,load_json,file_lock,utc_now,ROOT

class Ledger:
    def __init__(self,folder=None):
        self.folder=Path(folder or ROOT/'records/private').resolve()
        self.path=self.folder/'events.jsonl'

    def _events(self):
        if not self.path.exists():return []
        events=[];previous='0'*64;ids=set()
        for line_number,line in enumerate(self.path.read_text('utf-8').splitlines(),1):
            if not line:raise ValueError(f'Empty ledger line {line_number}')
            event=json.loads(line)
            claimed=event.pop('event_hash',None)
            if sha(canonical(event))!=claimed or event.get('previous_hash')!=previous or event.get('sequence')!=line_number or event.get('event_id') in ids:
                raise ValueError(f'Ledger hash/sequence mismatch at line {line_number}')
            event['event_hash']=claimed;events.append(event);previous=claimed;ids.add(event['event_id'])
        return events

    def replay(self):
        events=self._events()
        if not events:raise ValueError('尚未初始化学情；先运行 init。没有合成成绩自动填入。')
        if events[0]['kind']!='GENESIS':raise ValueError('Missing genesis')
        state=copy.deepcopy(events[0]['payload'])
        for event in events[1:]:
            if event['kind']=='SECONDARY_AUDIT_IMPORTED':
                from .evidence import apply_audit
                apply_audit(state,event['payload'])
                continue
            if event['kind']!='DAILY_RETURN_IMPORTED':raise ValueError('Unknown history event')
            self._apply(state,event['payload']['card'],event['payload']['card_hash'],event['payload'].get('node_links',{}))
        state['ledger_head']=events[-1]['event_hash'];state['ledger_events']=len(events)
        state['source_state_hash']=self.state_hash(state)
        return state

    @staticmethod
    def state_hash(state):
        return sha(canonical({k:v for k,v in state.items() if k not in ('ledger_head','ledger_events','source_state_hash')}))

    def _append(self,events,kind,payload):
        event={'sequence':len(events)+1,'event_id':sha(canonical({'kind':kind,'payload':payload})),'previous_hash':events[-1]['event_hash'] if events else '0'*64,'kind':kind,'recorded_at':utc_now(),'payload':payload}
        event['event_hash']=sha(canonical(event))
        atomic_write(self.path,''.join(canonical(e)+'\n' for e in events+[event]))

    def initialize(self,bank,record_kind='REAL'):
        if record_kind not in ('REAL','SYNTHETIC_TEST_ONLY'):raise ValueError('Unknown record kind')
        with file_lock(self.folder):
            if self.path.exists():
                state=self.replay()
                if state['record_kind']!=record_kind:raise ValueError('真实/合成账本不可混用')
                return state
            pilot=bank.pilot_summary()
            exposure={}
            for item in bank.items():
                if item.get('initial_exposure') in ('CONFIRMED_SEEN','UNKNOWN_POSSIBLY_EXPOSED','UNKNOWN_REQUIRES_EVIDENCE'):
                    exposure[item['id']]={'state':'CONFIRMED_SEEN' if item['initial_exposure']=='CONFIRMED_SEEN' else 'UNKNOWN_POSSIBLY_EXPOSED','source':'MIGRATED_SECONDARY_EVIDENCE','at':None}
            nodes={n.get('node_id',n.get('id')):{'name':n.get('ability_name',n.get('name')),'dimensions':{d:'INSUFFICIENT_EVIDENCE' for d in ('R','T','M','C','F')},'observations':[]} for n in bank.nodes()}
            initial={'version':'1.0','record_kind':record_kind,'history_summary':pilot,'attempts':{},'exposures':exposure,'repairs':{},'retests':{},'nodes':nodes,'event_ids':{},'imported_returns':{},'last_training_date':None}
            if pilot:
                initial['repairs']={'PILOT-Q03':{'status':'PROMPT_GENERATED_NOT_TRAINED','topic':'Q03','actual_answers':[]},'PILOT-Q06':{'status':'PROMPT_GENERATED_NOT_TRAINED','topic':'Q06','actual_answers':[]}}
            self._append([],'GENESIS',initial)
            state=self.replay();write_json(self.folder/'state.json',state);return state

    @staticmethod
    def _apply(state,card,card_hash,node_links=None):
        if card_hash in state['imported_returns']:return
        for p in card['presented_items']:
            prior=state['exposures'].get(p['item_id'],{}).get('state')
            reported=p['exposure']
            state['exposures'][p['item_id']]={'state':'CONFIRMED_SEEN' if prior=='CONFIRMED_SEEN' else reported,'source':'CHATGPT_RETURN_REPORTED_PRESENTATION','at':p.get('presented_at')}
        for a in card['attempts']:
            if a['attempt_id'] in state['attempts']:
                old=state['attempts'][a['attempt_id']]
                if canonical({k:v for k,v in old.items() if k!='supplements'})!=canonical({k:v for k,v in a.items() if k!='supplements'}):raise ValueError('不可覆盖既有首答')
                if a['supplements'][:len(old['supplements'])]!=old['supplements']:raise ValueError('不能覆盖已封存补页')
            state['attempts'][a['attempt_id']]=copy.deepcopy(a)
            for node in (node_links or {}).get(a['attempt_id'],[]):
                if node not in state['nodes']:raise ValueError('Unknown node in imported observation')
                row=state['nodes'][node]
                if not any(o['attempt_id']==a['attempt_id'] for o in row['observations']):
                    row['observations'].append({'attempt_id':a['attempt_id'],'date':card['date'],'grade_status':a['grade']['status'],'score':a['grade']['score'],'completion':a['completion'],'hint_level':a['hint_level'],'evidence_level':'FORMATIVE_REPORTED_NOT_CERTIFIED'})
                for dimension,value in a['grade'].get('dimensions',{}).items():
                    if dimension in row['dimensions'] and value:row['dimensions'][dimension]='FORMATIVE_OBSERVATION:'+str(value)
        for event in card['repair_events']:
            if event['event_id'] in state.setdefault('event_ids',{}):raise ValueError('跨结转重复互动事件ID')
            state['event_ids'][event['event_id']]='REPAIR'
            row=state['repairs'].setdefault(event['repair_id'],{'status':'PLANNED','actual_answers':[]})
            row['status']=event['status']
            if event.get('actual_answer'):row['actual_answers'].append({'event_id':event['event_id'],'raw':event['actual_answer'],'at':event.get('at')})
        for event in card['retest_events']:
            if event['event_id'] in state.setdefault('event_ids',{}):raise ValueError('跨结转重复复测事件ID')
            state['event_ids'][event['event_id']]='RETEST'
            row=state['retests'].setdefault(event['cohort_id'],{'events':[],'certified_h0':False,'certified_m4':False})
            row['events'].append(copy.deepcopy(event))
        state['imported_returns'][card_hash]={'release_id':card['release_id'],'date':card['date'],'attempt_count':len(card['attempts'])}
        state['last_training_date']=card['date']
        state.pop('pending_audit_release_bases',None)

    def import_return(self,card,release,bank,inject_failure=False,assets=None,return_source=None):
        from .returns import validate_return
        card_hash=sha(canonical(card))
        with file_lock(self.folder):
            state=self.replay()
            if card_hash in state['imported_returns']:return {'status':'IDEMPOTENT_ALREADY_IMPORTED','card_hash':card_hash,'state_hash':state['source_state_hash']}
            if release.get('bank_hash')!=bank.hash:raise ValueError('题库版本与发布包不一致')
            if canonical(self.release(release['release_id']))!=canonical(release):raise ValueError('发布上下文与本地登记不一致')
            validated=validate_return(card,release,{i['id']:i for i in bank.items()},state)
            if validated['errors']:raise ValueError('结转拒绝：'+'; '.join(str(x) for x in validated['errors']))
            normalized=validated.get('normalized',card)
            for e in normalized['repair_events']+normalized['retest_events']:
                if e['event_id'] in state.get('event_ids',{}):raise ValueError('跨结转重复事件ID：'+e['event_id'])
            if state.get('last_training_date') and normalized['date'] < state['last_training_date']:raise ValueError('不可倒写已结转学习日期')
            events=self._events()
            if inject_failure:raise OSError('SYNTHETIC failure before atomic history commit')
            asset_evidence={}
            for a in normalized['attempts']:
                for answer in [a['first_answer']]+a['supplements']:
                    for reference in answer['assets']:
                        raw=(assets or {}).get(reference['path'])
                        if not isinstance(raw,bytes) or sha(raw)!=reference['sha256']:raise ValueError('ASSET_BYTES_MISSING_OR_MISMATCH: '+reference['path'])
                        relative='assets/'+reference['sha256']+'.bin'
                        atomic_bytes(self.folder/relative,raw)
                        asset_evidence[reference['path']]={'stored_path':relative,'sha256':reference['sha256'],'bytes':len(raw)}
            source_artifact=None
            if return_source:
                raw=return_source['bytes'];suffix=return_source.get('suffix','.json')
                if suffix not in ('.zip','.json'):raise ValueError('Invalid source artifact type')
                relative='source_returns/'+sha(raw)+suffix
                atomic_bytes(self.folder/relative,raw)
                source_artifact={'path':relative,'sha256':sha(raw),'bytes':len(raw)}
            from .quality import answered_nodes
            self._append(events,'DAILY_RETURN_IMPORTED',{'card_hash':card_hash,'card':normalized,'asset_evidence':asset_evidence,'source_artifact':source_artifact,'node_links':{a['attempt_id']:sorted(answered_nodes(bank.get(a['item_id']),a)) for a in normalized['attempts']}})
            rebuilt=self.replay();write_json(self.folder/'state.json',rebuilt)
            write_json(self.folder/'returns'/f'{card_hash}.json',normalized)
            return {'status':'IMPORTED_FORMATIVE_ONLY','card_hash':card_hash,'attempt_count':len(normalized['attempts']),'warnings':validated['warnings'],'state_hash':rebuilt['source_state_hash']}

    def register_release(self,release):
        with file_lock(self.folder):
            path=self.folder/'releases'/f"{release['release_id']}.json"
            if path.exists() and canonical(load_json(path))!=canonical(release):raise ValueError('发布ID已绑定不同内容')
            write_json(path,release)

    def release(self,release_id):
        if not release_id.replace('_','').replace('-','').isalnum():raise ValueError('Invalid release ID')
        return load_json(self.folder/'releases'/f'{release_id}.json')

    def export(self,output):
        state=self.replay();write_json(output,state);return state
