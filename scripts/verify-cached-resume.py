#!/usr/bin/env python3
"""Replay a completed run in an isolated copy, with all model calls forbidden.

The original run and API configuration are never changed. This needs no key and
does not contact the configured endpoint. Only aggregate results are printed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chigua import core, pipeline, provider, report
from chigua.checkpoints import usage_summary


def snapshot(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def verify(run_id, recover_raw=False):
    if not run_id.isalnum():
        raise ValueError('Invalid run ID')
    original = core.DATA / 'runs' / run_id
    manifest = json.loads((original / 'manifest.json').read_text())
    result = json.loads((original / 'result.json').read_text())
    case = json.loads((original / 'input.json').read_text())
    assert result['status'] == 'completed'
    before = snapshot(original)
    original_usage = usage_summary(original)
    config = manifest['config']
    env = {'CHIGUA_PROVIDER': config['provider'], 'CHIGUA_MODEL': config['model'],
           'CHIGUA_BASE_URL': config['base_url'], 'CHIGUA_API_KEY': 'offline-test-no-secret'}
    with tempfile.TemporaryDirectory(prefix='chigua-resume-check-') as temp:
        isolated = Path(temp)
        target = isolated / 'runs' / run_id
        shutil.copytree(original, target)
        core.write_json(isolated / 'cases' / (case['id'] + '.json'), case)
        (isolated / 'uploads').mkdir()
        for name in {m['image'] for m in case['messages'] if m.get('image')}:
            assert Path(name).name == name
            shutil.copyfile(core.DATA / 'uploads' / name, isolated / 'uploads' / name)
        # Simulate a restart before final publication, with only durable data.
        (target / 'result.json').unlink()
        job = json.loads((target / 'job.json').read_text())
        job.update(status='running', error='', uncertain=False)
        core.write_json(target / 'job.json', job)
        recovered_attempt = None
        if recover_raw:
            cache = next(target.rglob('completed.json'))
            recovered_attempt = sorted(cache.parent.glob('attempt-*/attempt.json'))[-1]
            assert (recovered_attempt.parent / 'raw-response.json').is_file()
            attempt = json.loads(recovered_attempt.read_text())
            attempt['status'] = 'running'
            core.write_json(recovered_attempt, attempt)
            cache.unlink()
        assert not pipeline.JOBS, 'Run this check in a fresh process'
        with patch.dict(os.environ, env), patch.object(core, 'DATA', isolated), \
                patch.object(pipeline, 'DATA', isolated), patch.object(provider, 'DATA', isolated), \
                patch.object(report, 'DATA', isolated), \
                patch.object(provider, 'config_identity', return_value=config), \
                patch.object(provider, '_generate_once', side_effect=AssertionError('Model call forbidden')) as model, \
                patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')) as network:
            assert pipeline.get_job(run_id)['status'] == 'interrupted'
            resumed = pipeline.resume(run_id, allow_uncertain=True, background=False)
            assert resumed['status'] == 'completed', resumed.get('error')
            model.assert_not_called()
            network.assert_not_called()
            assert resumed['usage'] == original_usage
            assert resumed['result']['report'] == result['report']
            assert all(row['cached'] for row in resumed['result']['trace'] + resumed['result']['editorial_trace'])
            if recovered_attempt:
                assert json.loads(recovered_attempt.read_text())['recovered_response'] is True
        pipeline.JOBS.clear()
    assert snapshot(original) == before, 'Original run changed during isolated test'
    return {'mode': 'received_response_recovery' if recover_raw else 'process_restart',
            'status': 'passed', 'new_model_requests': 0, 'new_network_requests': 0,
            'additional_input_tokens': 0, 'additional_output_tokens': 0,
            'original_unchanged': True, 'usage': original_usage}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    parser.add_argument('--recover-raw', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.run_id, args.recover_raw), ensure_ascii=False))
