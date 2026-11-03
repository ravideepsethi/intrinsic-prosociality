"""Check launcher wiring without running analysis or changing the user's HOME."""
from pathlib import Path
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='iv106_launcher_') as temporary:
        root=Path(temporary);desktop=root/'Lichess Desktop';package=root/'Package With Spaces'
        package.mkdir();env=desktop/'MatingMaterial_IV_Env_v100';(env/'bin').mkdir(parents=True)
        requirements=(ROOT/'requirements.txt').read_bytes()
        (package/'requirements.txt').write_bytes(requirements)
        (env/'REQUIREMENTS_SHA256').write_text(hashlib.sha256(requirements).hexdigest()+'\n')
        (package/'run.py').write_text('# Smoke-test placeholder; real analysis is not invoked.\n')
        stub=env/'bin/python'
        stub.write_text('#!'+sys.executable+'\n'+'''import os,sys,json
if sys.argv[1:3]==['-m','unittest']:
    print('SYNTHETIC_COMPLETE_MARKER_MUST_STAY_IN_LOG')
    print('----------------------------------------------------------------------')
    print('Ran 108 tests in 0.001s')
    print('')
    print('FAILED' if os.environ.get('IV_SMOKE_FAIL') else 'OK')
    raise SystemExit(13 if os.environ.get('IV_SMOKE_FAIL') else 0)
print('PRODUCTION_INVOKED '+json.dumps(sys.argv[1:]))
''')
        stub.chmod(0o755)
        launcher=(ROOT/'RUN_IV_RESUME.command').read_text()
        needle='iv_desktop="$HOME/Desktop/Lichess_Desktop"'
        assert launcher.count(needle)==1
        launcher=launcher.replace(needle,'iv_desktop='+shlex.quote(str(desktop)))
        target=package/'RUN_IV_RESUME.command';target.write_text(launcher)
        args=['bash',str(target),'--preflight-only','--workers','5']
        good=subprocess.run(args,text=True,capture_output=True)
        assert good.returncode==0,good.stdout+good.stderr
        assert 'SYNTHETIC_COMPLETE_MARKER' not in good.stdout
        assert 'Starting the production resume now' in good.stdout
        invocation=json.loads(next(line.split('PRODUCTION_INVOKED ',1)[1] for line in good.stdout.splitlines() if line.startswith('PRODUCTION_INVOKED ')))
        assert invocation==['-u',str(package/'run.py'),'--result-dir',str(desktop),'--preflight-only','--workers','5']
        bad=subprocess.run(args,text=True,capture_output=True,env=dict(os.environ,IV_SMOKE_FAIL='1'))
        assert bad.returncode!=0 and 'PRODUCTION_INVOKED' not in bad.stdout
        assert 'Startup tests failed; production has not started.' in bad.stdout
        assert all('SYNTHETIC_COMPLETE_MARKER' in p.read_text() for p in (desktop/'Logs').iterdir())
        (ROOT/'validation/resume106_launcher_smoke.log').write_text('SUCCESS CASE\n'+good.stdout+'\nFAILURE CASE\n'+bad.stdout)
    result=dict(result='PASS',paths_with_spaces=True,completed_test_messages_hidden=True,
                test_failure_blocks_production=True,arguments_forwarded=True,
                log='validation/resume106_launcher_smoke.log')
    (ROOT/'validation/resume106_launcher_smoke.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
