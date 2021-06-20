import sys

if __name__ == '__main__':
    # workflow = sys.argv[1]  # nightly_build or PR
    # job_to_test = sys.argv[2]
    job_to_test = sys.argv[1]

    with open(".github/workflows/jobs_to_run.txt", 'r') as file:
        filedata = file.read()

    print(True) if job_to_test in filedata else print(False)
