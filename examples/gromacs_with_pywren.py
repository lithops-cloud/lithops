"""
Example of running GROMACS with lithops
"""

import lithops
import os
import zipfile
import time
import wget
import json

temp_dir = '/tmp'
iterdata = [1]


def sh_cmd_executor(x, param1, ibm_cos):
    lithops_config = json.loads(os.environ['LITHOPS_CONFIG'])
    bucket = lithops_config['lithops']['storage_bucket']
    print (bucket)
    print (param1)
    filename = 'benchMEM.zip'
    outfile = os.path.join(temp_dir, filename)

    if not os.path.isfile(filename):
        filename = wget.download('https://www.mpibpc.mpg.de/15101317/benchMEM.zip', out=outfile)
        print(filename, "was downloaded")
        with zipfile.ZipFile(outfile, 'r') as zip_ref:
            print('Extracting file to %s' % temp_dir)
            zip_ref.extractall(temp_dir)
    else:
        print(filename, " already exists")

    os.chdir(temp_dir)
    cmd = "/usr/local/gromacs/bin/gmx mdrun -nt 4 -s benchMEM.tpr -nsteps 1000 -resethway"

    st = time.time()
    import subprocess
    subprocess.call(cmd, shell=True)
    run_time = time.time() - st

    # upload results to IBM COS
    res = ['confout.gro', 'ener.edr', 'md.log',  'state.cpt']
    for name in res:
        f = open(os.path.join(temp_dir, name), "rb")
        ibm_cos.put_object(Bucket=bucket, Key=os.path.join('gmx-mem', name), Body=f)

    with open('md.log', 'r') as file:
        data = file.read()

    return {'run_time': run_time, 'md_log': data}


if __name__ == '__main__':
    # Example of using bechMEM from https://www.mpibpc.mpg.de/grubmueller/bench

    param1 = 'param1 example'

    total_start = time.time()
    fexec = lithops.FunctionExecutor(runtime='cactusone/lithops-gromacs:1.0.2', runtime_memory=2048)
    fexec.map(sh_cmd_executor, iterdata, extra_args=(param1,))
    res = fexec.get_result()
    fexec.clean()

    print ("GROMACS execution time {}".format(res[0]['run_time']))
    print ("Total execution time {}".format(time.time()-total_start))
    print (res[0]['md_log'])
