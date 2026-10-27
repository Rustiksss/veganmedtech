import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from scripts.collect_metrics import access_metrics, byte_size, collect_host, make_report, summary, validate_scenario


class MetricsTests(unittest.TestCase):
    def test_latency_units_empty_data_and_safe_log_filter(self):
        self.assertIsNone(summary([])['p95_ms'])
        self.assertEqual(summary([0,1,2,float('nan'),-1])['samples'],3)
        self.assertEqual(summary(range(1,21))['p95_ms'],19)
        data=access_metrics('2026-10-27T12:00:00.123456789Z GET 200 1500\nPOST 503 8000\nGET /private?email=SECRET 200 1\nAuthorization: SECRET')
        self.assertEqual(data['requests_observed'],2)
        self.assertEqual(data['latency']['p50_ms'],4.75)
        self.assertEqual(data['server_error_fraction'],.5)
        self.assertNotIn('SECRET',json.dumps(data))
        self.assertFalse(data['coverage_complete'])
        self.assertEqual(byte_size(' 1.5MiB '),1572864)

    def test_all_thirteen_directions_and_missing_measurements(self):
        report=make_report({'sources':{'app':'unavailable'}},24)
        self.assertEqual([m['requirement'] for m in report['metrics']],[f'NFR-{n:03}' for n in range(1,14)])
        self.assertEqual(report['metrics'][1]['status'],'not_implemented')
        self.assertIsNone(report['metrics'][1]['data']['precision'])
        self.assertEqual(report['metrics'][3]['status'],'not_measured')
        self.assertEqual(report['metrics'][2]['status'],'unavailable')
        self.assertIsNone(report['metrics'][10]['data']['probe_ms'])

    def test_unavailable_sources_do_not_export_errors_or_fake_zeroes(self):
        with patch('scripts.collect_metrics.command',side_effect=RuntimeError('SECRET')):
            with patch('scripts.collect_metrics.Path.glob',side_effect=OSError('SECRET')):
                with patch('scripts.collect_metrics.urllib.request.urlopen',side_effect=OSError('SECRET')):
                    data=collect_host(24)
        self.assertTrue(all(v=='unavailable' for v in data['sources'].values()))
        self.assertTrue(all(data[k] is None for k in data['sources']))
        self.assertNotIn('SECRET',json.dumps(make_report(data,24)))

    def test_scenario_import_filters_private_fields_and_rejects_invalid_values(self):
        value={'scenario':'self_report','duration_ms':1200,'activation_count':2,'field_change_count':1,
               'viewport_width':390,'viewport_height':844,'browser':'Firefox','email':'SECRET','cookie':'SECRET','text':'SECRET'}
        safe=validate_scenario(value)
        self.assertNotIn('SECRET',json.dumps(safe))
        with self.assertRaises(ValueError):validate_scenario([])
        for change in [{'scenario':'patient-SECRET'},{'duration_ms':-1},{'duration_ms':float('inf')},{'activation_count':True}]:
            with self.assertRaises(ValueError):validate_scenario({**value,**change})

    def test_browser_start_stop_and_events_without_reading_field_values(self):
        node=os.environ.get('METRICS_NODE') or shutil.which('node')
        if not node:self.skipTest('Node required for this isolated JS check')
        script=Path(__file__).resolve().parents[1]/'scripts/measure_scenario.js'
        code=r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const handlers=new Map();let now=100,printed=[];
const context={window:{},document:{addEventListener:(k,v)=>handlers.set(k,v),removeEventListener:(k,v)=>{if(handlers.get(k)===v)handlers.delete(k)}},
 performance:{now:()=>now},navigator:{userAgent:'PRIVATE-SECRET Firefox/157'},innerWidth:390,innerHeight:844,
 console:{log:x=>printed.push(x)},fetch:()=>{throw new Error('Network forbidden')}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const api=context.window.CompassScenario;
assert.throws(()=>api.stop());assert.throws(()=>api.start('patient-SECRET'));
api.start('self_report');
const event={get target(){throw new Error('Field access forbidden')}};
handlers.get('click')(event);handlers.get('change')(event);now=1300;
const result=JSON.parse(JSON.stringify(api.stop()));
assert.equal(result.duration_ms,1200);assert.equal(result.activation_count,1);assert.equal(result.field_change_count,1);
assert.equal(result.browser,'Firefox');assert.equal(handlers.size,0);assert.ok(!JSON.stringify(result).includes('SECRET'));
api.start('login');api.start('view_history');handlers.get('click')(event);
assert.equal(api.stop().activation_count,1);assert.equal(handlers.size,0);
console.log('Browser start/stop/privacy OK');
'''
        result=subprocess.run([node,'-e',code,str(script)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
