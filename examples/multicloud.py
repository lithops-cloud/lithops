"""
Simple Lithops example using multiple clouds
"""
from lithops import FunctionExecutor
from lithops import get_result


def double(i):
    return i * 2

if __name__ == '__main__':
    fexec_aws = FunctionExecutor(backend='aws_lambda', storage='aws_s3')
    futures_aws = fexec_aws.map(double, [1, 2, 3, 4])

    fexec_ibm = FunctionExecutor(backend='ibm_cf', storage='ibm_cos')
    futures_ibm = fexec_ibm.map(double, [5, 6, 7, 8])

    print(get_result(futures_aws + futures_ibm))
