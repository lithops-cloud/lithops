"""
Simple Lithops example using the 'ibm_cos' parameter, which is
a ready-to-use ibm_boto3.CLient() instance.
"""
import lithops


def my_function(bucket_name, key, ibm_cos):
    print(f'I am processing the object cos://{bucket_name}/{key}')
    counter = {}

    data = ibm_cos.get_object(Bucket=bucket_name, Key=key)['Body'].read()

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1

    return counter


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function, ('lithops-sample-data', 'obj1.txt'))
    print(fexec.get_result())
