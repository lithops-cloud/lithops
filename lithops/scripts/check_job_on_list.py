import sys

if __name__ == '__main__':
    workflow = sys.argv[1]  # PR or nightly_build

    with open(".github/workflows/jobs_to_run.txt", 'r') as file:
        filedata = file.read().split('\n')

    filedata = [item for item in filedata if '#' not in item and item != '']

    if workflow == 'PR git-action':
        print(filedata[filedata.index('on_PR:') + 1:filedata.index('nightly_build:')])

    else:  # workflow == 'Nightly Build'
        print(filedata[filedata.index('nightly_build:') + 1:])


